"""Discord marketplace submissions and a private, core-authorized local projection."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import nextcord
from nextcord.ext import commands, tasks

from src.core.lifecycle import spawn
from src.database.database import db
from src.services.guild_modules_service import guild_modules_service
from src.services.guild_settings_service import guild_settings_service
from src.services.marketplace_core import CoreError, configured_sync
from src.services.marketplace_images import image_store
from src.services.marketplace_ingestion import MarketplaceIngestion
from src.services.marketplace_service import validate_price
from src.utils.embed_limits import clip_text
from src.utils.outbound import outbound
from src.utils.safety import bot_operator_only, safe_command, safe_send, safe_slash_command
from src.utils.security import rate_limit

logger = logging.getLogger('VEKA.marketplace')


class Marketplace(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sync = configured_sync()
        self.ingestion = MarketplaceIngestion(self.sync)
        self._ticks = 0
        self._observation_lock = asyncio.Lock()

    @nextcord.slash_command(name='marketplace', description='Community classifieds and explicit submissions')
    async def marketplace(self, interaction: nextcord.Interaction):
        await safe_send(
            interaction,
            content='Post, submit, browse, view, mylistings, search, withdraw or bump. Publication requires core review and consent.',
            ephemeral=True,
        )

    async def cog_ready(self):
        if not self.sync.client.configured:
            logger.warning('Marketplace core integration is unconfigured; submission/publication disabled')
            return
        await self.sync.refresh_bindings()
        if not self.sync_loop.is_running():
            self.sync_loop.start()
        # Bounded discovery only in explicitly bound forums. Known sources are reconciled too.
        remaining = 100
        for guild in self.bot.guilds:
            for forum in guild.forums:
                if not await self.sync.binding(guild.id, forum.id):
                    continue
                for thread in forum.threads:
                    if remaining <= 0:
                        return
                    await self._ingest_forum_thread(thread)
                    remaining -= 1

    def cog_unload(self):
        self.sync_loop.cancel()
        if self.sync.client.session is not None:
            spawn(self.sync.client.close(), name='marketplace:close')

    @tasks.loop(seconds=10)
    async def sync_loop(self):
        tick = self._ticks
        self._ticks += 1
        try:
            if tick % 6 == 0:
                await self.sync.refresh_bindings()
            for _ in range(3):
                if not await self.sync.deliver_one():
                    break
            if tick % 30 == 0:
                await self.sync.reconcile()
                await self._reconcile_discord()
            async with asyncio.timeout(240):
                await self.sync.poll_events(self._deliver_event)
        except CoreError as exc:
            logger.warning('Marketplace integration unavailable (%s); durable work retained', exc.code)
        except Exception as exc:
            logger.warning('Marketplace worker failed (%s); durable work retained', type(exc).__name__)

    @staticmethod
    def _forum_price(name: str, content: str) -> Decimal | None:
        amount, _ = Marketplace._price(name, content)
        return amount

    @staticmethod
    def _price(name: str, content: str):
        # Dollar signs mean USD; INR/AED must be explicit. Never guess model numbers.
        pattern = r'(?:(?<!\w)(USD|AED|INR)\s*|\$\s*)([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)(?![0-9.,eE])|(?<![0-9A-Za-z.,])([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)\s*(USD\b|AED\b|INR\b|\$)'
        match = re.search(pattern, name, re.I) or re.search(pattern, content, re.I)
        if not match:
            return None, None
        raw = match.group(2) or match.group(3)
        currency = (match.group(1) or match.group(4) or 'USD').upper().replace('$', 'USD')
        try:
            return validate_price(raw.replace(',', '')), currency
        except ValueError:
            return None, None

    async def _ingest_forum_thread(self, thread):
        async with self._observation_lock:
            if not await guild_modules_service.enabled(thread.guild.id, 'marketplace'):
                return
            binding = await self.sync.binding(thread.guild.id, thread.parent_id)
            if not binding or binding['mode'] != 'forum':
                return
            if await db.fetchval('SELECT 1 FROM marketplace_core_publications WHERE message_id=$1', thread.id):
                return
            listing_id = f'MP{thread.id}'
            if thread.archived or thread.locked:
                await self.ingestion.source_state(listing_id, 'archived' if thread.archived else 'locked')
                return
            try:
                starter = await thread.fetch_message(thread.id)
                if starter.author.bot or starter.webhook_id is not None or thread.owner_id is None:
                    return
                tags = {str(tag.id) for tag in thread.applied_tags}
                category = next(
                    (m['category_id'] for m in binding.get('tag_categories', []) if m['tag_id'] in tags),
                    binding.get('default_category_id'),
                )
                price, currency = self._price(thread.name, starter.content)
                await self.ingestion.save(
                    guild_id=thread.guild.id,
                    channel_id=thread.parent_id,
                    message_id=thread.id,
                    author_id=starter.author.id,
                    source_kind='forum',
                    title=thread.name[:100],
                    description=starter.content,
                    price=price,
                    currency=currency,
                    category_id=category,
                    attachments=starter.attachments,
                    edited_at=starter.edited_at,
                )
            except nextcord.NotFound:
                await self.ingestion.source_state(listing_id, 'deleted')
            except (nextcord.Forbidden, ValueError):
                # Incomplete media/source visibility must hide, not publish stale removed photos.
                await self.ingestion.source_state(listing_id, 'unavailable')

    async def _refresh_source(self, source):
        guild = self.bot.get_guild(source['guild_id'])
        if guild is None:
            await self.ingestion.source_state(source['listing_id'], 'unavailable')
            return
        try:
            if source['source'] == 'forum':
                thread = guild.get_thread(source['message_id']) or await guild.fetch_channel(source['message_id'])
                if isinstance(thread, nextcord.Thread):
                    await self._ingest_forum_thread(thread)
            elif source['source'] == 'text':
                channel = guild.get_channel(source['channel_id'])
                if not isinstance(channel, nextcord.TextChannel):
                    await self.ingestion.source_state(source['listing_id'], 'unavailable')
                    return
                message = await channel.fetch_message(source['message_id'])
                await self._submit_message(message, consent=None)
        except nextcord.NotFound:
            await self.ingestion.source_state(source['listing_id'], 'deleted')
        except (nextcord.Forbidden, ValueError):
            await self.ingestion.source_state(source['listing_id'], 'unavailable')

    async def _reconcile_discord(self):
        marker = await db.fetchval('SELECT discord_cursor FROM marketplace_core_consumer WHERE id=TRUE')
        sources = await db.fetch(
            'SELECT s.*,l.source FROM marketplace_core_sources s JOIN marketplace_listings l ON l.id=s.listing_id '
            "WHERE s.listing_id>$1 AND l.source IN ('forum','text') AND NOT s.tombstone ORDER BY s.listing_id LIMIT 25",
            marker,
        )
        for source in sources:
            await self._refresh_source(source)
            await db.execute(
                'UPDATE marketplace_core_consumer SET discord_cursor=$1 WHERE id=TRUE', source['listing_id']
            )
        if len(sources) < 25:
            await db.execute("UPDATE marketplace_core_consumer SET discord_cursor='' WHERE id=TRUE")

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        await self._ingest_forum_thread(thread)

    @commands.Cog.listener()
    async def on_thread_update(self, before, after):
        if (before.name, before.applied_tags, before.archived, before.locked) != (
            after.name,
            after.applied_tags,
            after.archived,
            after.locked,
        ):
            await self._ingest_forum_thread(after)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread):
        await self.ingestion.source_state(f'MP{thread.id}', 'deleted')

    @commands.Cog.listener()
    async def on_message(self, message):
        # Forum starter fallback only. Ordinary text chat is NEVER collected.
        if isinstance(message.channel, nextcord.Thread) and message.id == message.channel.id and not message.author.bot:
            await self._ingest_forum_thread(message.channel)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        source = await db.fetch_one(
            'SELECT s.*,l.source FROM marketplace_core_sources s JOIN marketplace_listings l ON l.id=s.listing_id WHERE s.message_id=$1',
            payload.message_id,
        )
        if source:
            await self._refresh_source(source)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        source = await db.fetch_one(
            'SELECT listing_id FROM marketplace_core_sources WHERE message_id=$1', payload.message_id
        )
        if source:
            await self.ingestion.source_state(source['listing_id'], 'deleted')

    @marketplace.subcommand(name='post', description='Submit an item for review (not automatically public)')
    @rate_limit('marketplace')
    @safe_slash_command(requires_db=True)
    async def mp_post(
        self,
        interaction,
        title: str,
        price: str,
        category: str,
        description: str = '',
        currency: str = nextcord.SlashOption(choices=['USD', 'AED', 'INR']),
        public: bool = False,
        image: nextcord.Attachment | None = None,
    ):
        if interaction.guild is None:
            await safe_send(interaction, content='Use this command inside a configured server.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            channel, binding = await self._destination(interaction)
            if channel is None or binding is None:
                raise ValueError('Choose a readable, writable marketplace channel with an enabled core binding.')
            listing_id = await self.ingestion.save(
                guild_id=interaction.guild.id,
                channel_id=channel.id,
                message_id=interaction.id,
                author_id=interaction.user.id,
                source_kind='command',
                title=title,
                description=description,
                price=validate_price(price),
                currency=currency,
                category_id=str(uuid.UUID(category)),
                attachments=[image] if image else [],
                consent=self.ingestion.consent(
                    interaction, 'public' if public else 'community', binding['policy_version']
                ),
            )
            await safe_send(
                interaction,
                content=f'Listing `{listing_id}` queued for core review. It is not published yet.',
                ephemeral=True,
            )
        except ValueError as exc:
            await safe_send(interaction, content=str(exc), ephemeral=True)

    async def _destination(self, interaction):
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return None, None
        current = interaction.channel
        if isinstance(current, nextcord.Thread):
            current = interaction.guild.get_channel(current.parent_id)
        fallback = await guild_settings_service.resolve_channel(interaction.guild, 'marketplace_channel_id')
        for channel in (current, fallback):
            if (
                not isinstance(channel, (nextcord.TextChannel, nextcord.ForumChannel))
                or channel.guild.id != interaction.guild.id
            ):
                continue
            permissions = channel.permissions_for(interaction.user)
            if not permissions.view_channel or not permissions.send_messages:
                continue
            binding = await self.sync.binding(interaction.guild.id, channel.id)
            if binding:
                return channel, binding
        return None, None

    @mp_post.on_autocomplete('category')
    async def category_autocomplete(self, interaction, category: str):
        _, binding = await self._destination(interaction)
        choices = (
            {
                c['name'][:100]: c['id']
                for c in binding['categories']
                if c['active'] and category.casefold() in c['name'].casefold()
            }
            if binding
            else {}
        )
        await interaction.response.send_autocomplete(dict(list(choices.items())[:25]))

    @marketplace.subcommand(name='submit', description='Explicitly submit your own text-channel message for review')
    @rate_limit('marketplace')
    @safe_slash_command(requires_db=True)
    async def mp_submit(self, interaction, message_id: str, public: bool = False):
        await interaction.response.defer(ephemeral=True)
        try:
            if (
                not interaction.guild
                or not isinstance(interaction.channel, nextcord.TextChannel)
                or not message_id.isdecimal()
            ):
                raise ValueError('Use this inside the bound text marketplace channel with your message ID.')
            message = await interaction.channel.fetch_message(int(message_id))
            if message.author.id != interaction.user.id or message.author.bot or message.webhook_id:
                raise ValueError('You can submit only your own message.')
            binding = await self.sync.binding(interaction.guild.id, interaction.channel.id)
            if not binding or binding['mode'] != 'text':
                raise ValueError('This is not a bound text marketplace channel.')
            consent = self.ingestion.consent(
                interaction, 'public' if public else 'community', binding['policy_version']
            )
            listing_id = await self._submit_message(message, consent)
            await safe_send(
                interaction,
                content=f'`{listing_id}` submitted for review. Ordinary chat is never imported.',
                ephemeral=True,
            )
        except (ValueError, nextcord.NotFound, nextcord.Forbidden) as exc:
            await safe_send(
                interaction, content=str(exc) if isinstance(exc, ValueError) else 'Message unavailable.', ephemeral=True
            )

    async def _submit_message(self, message, consent):
        async with self._observation_lock:
            binding = await self.sync.binding(message.guild.id, message.channel.id)
            if (
                not binding
                or binding['mode'] != 'text'
                or not await guild_modules_service.enabled(message.guild.id, 'marketplace')
            ):
                raise ValueError('Text submissions are disabled here.')
            if message.author.bot or message.webhook_id:
                raise ValueError('Bot/webhook messages are not submissions.')
            # The /submit interaction is the explicit confirmation, not passive scraping.
            # Reconciliation only ever calls this for already-persisted submitted source IDs.
            title = message.content.splitlines()[0][:100] if message.content else ''
            price, currency = self._price(title, message.content)
            return await self.ingestion.save(
                guild_id=message.guild.id,
                channel_id=message.channel.id,
                message_id=message.id,
                author_id=message.author.id,
                source_kind='text',
                title=title,
                description=message.content,
                price=price,
                currency=currency,
                category_id=binding.get('default_category_id'),
                attachments=message.attachments,
                edited_at=message.edited_at,
                consent=consent,
            )

    @marketplace.subcommand(name='browse', description='Browse authorized listings in this server')
    @safe_slash_command(requires_db=True)
    async def mp_browse(self, interaction, category: str | None = None):
        try:
            rows = await self.ingestion.rows(interaction, category=category)
            await self._show_rows(interaction, rows)
        except ValueError:
            await safe_send(interaction, content='Choose a category from the current core taxonomy.', ephemeral=True)

    @marketplace.subcommand(name='view', description='Privately view a listing you may read')
    @safe_slash_command(requires_db=True)
    async def mp_view(self, interaction, listing_id: str):
        rows = await self.ingestion.rows(interaction, listing_id=listing_id)
        if not rows:
            await safe_send(interaction, content='Listing unavailable in this server.', ephemeral=True)
            return
        row = rows[0]
        embed = nextcord.Embed(title=clip_text(row['title'], 220), description=clip_text(row['description'], 3000))
        if row['core_listing_id']:
            embed.url = 'https://veka.gg/marketplace/' + str(row['core_listing_id'])
            embed.add_field(
                name='Seller and contact',
                value='Open the VEKA listing for its current seller contact options.',
                inline=False,
            )
        embed.add_field(
            name='Price', value=f'{row["price"]} {row["currency"]}' if row['price'] is not None else 'Ask seller'
        )
        embed.add_field(name='State', value=f'{row["status"]} / {row["core_moderation"]}')
        stored = await image_store.get(listing_id) if not row['image_missing'] else None
        if stored:
            embed.set_image(url='attachment://listing.webp')
        elif row['image_missing']:
            embed.add_field(
                name='Images', value='Open the canonical VEKA listing for its current gallery.', inline=False
            )
        await safe_send(interaction, embed=embed, file=stored.file() if stored else None, ephemeral=True)

    @marketplace.subcommand(name='mylistings', description='Your submissions in this server')
    @safe_slash_command(requires_db=True)
    async def mp_mylistings(self, interaction):
        await self._show_rows(interaction, await self.ingestion.rows(interaction, mine=True))

    @marketplace.subcommand(name='withdraw', description='Withdraw your listing through core')
    @safe_slash_command(requires_db=True)
    async def mp_withdraw(self, interaction, listing_id: str):
        await self._owner_action(interaction, listing_id, 'withdraw')

    @marketplace.subcommand(name='bump', description='Request an expiry renewal through core')
    @rate_limit('marketplace')
    @safe_slash_command(requires_db=True)
    async def mp_bump(self, interaction, listing_id: str):
        await self._owner_action(interaction, listing_id, 'renew')

    async def _owner_action(self, interaction, listing_id, action):
        try:
            if not interaction.guild:
                raise ValueError('Use this command in the listing’s server.')
            await self.ingestion.owner_action(
                listing_id, interaction.guild.id, interaction.user.id, interaction.id, action
            )
            await safe_send(
                interaction,
                content='Action queued. Core enforces ownership, lifecycle and renewal cooldown.',
                ephemeral=True,
            )
        except ValueError as exc:
            await safe_send(interaction, content=str(exc), ephemeral=True)

    @marketplace.subcommand(name='search', description='Search authorized listings in this server')
    @safe_slash_command(requires_db=True)
    async def mp_search(self, interaction, query: str):
        enhanced = self.bot.get_cog('MarketplaceEnhanced')
        if enhanced is None:
            await safe_send(interaction, content='Marketplace search is temporarily unavailable.', ephemeral=True)
            return
        await enhanced.search_slash(interaction, query)

    async def _show_rows(self, interaction, rows):
        embed = nextcord.Embed(title='Marketplace', description='No readable listings here.' if not rows else None)
        for row in rows[:10]:
            embed.add_field(
                name=clip_text(row['title'], 100),
                value=f'`{row["id"]}` · {row["price"] if row["price"] is not None else "Ask seller"} {row["currency"]} · {row["status"]}',
                inline=False,
            )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @commands.command(name='marketplace_sync')
    @bot_operator_only()
    @safe_command(requires_db=True)
    async def mp_sync(self, ctx):
        await self.sync.refresh_bindings()
        await self.sync.reconcile()
        await safe_send(
            ctx,
            content='Bindings/receipts reconciled. See core admin for permanent queue conflicts; no global cross-server republication occurs.',
        )

    @commands.command(name='marketplace_queue')
    @bot_operator_only()
    @safe_command(requires_db=True)
    async def mp_queue(self, ctx):
        rows = await db.fetch(
            'SELECT status,count(*) AS count,min(created_at) AS oldest FROM marketplace_core_outbox GROUP BY status ORDER BY status'
        )
        text = '; '.join(f'{r["status"]}: {r["count"]} (oldest {r["oldest"].isoformat()})' for r in rows)
        await safe_send(ctx, content=text or 'Marketplace queue is empty.')

    @commands.command(name='marketplace_retry')
    @bot_operator_only()
    @safe_command(requires_db=True)
    async def mp_retry(self, ctx, event_id: str):
        try:
            await self.sync.retry_event(event_id, ctx.author.id)
            await safe_send(
                ctx, content='Immutable event queued for retry; policy/revision conflicts need a fresh submission.'
            )
        except ValueError as exc:
            await safe_send(ctx, content=str(exc))

    async def _deliver_event(self, event):
        if event['type'] == 'listing.changed' and not event.get('delivery'):
            return  # Only update projection; never edit a member's source post.
        delivery = event.get('delivery')
        if not delivery:
            return
        guild = self.bot.get_guild(int(delivery['guild_id']))
        channel = guild.get_channel(int(delivery['channel_id'])) if guild else None
        if not isinstance(channel, (nextcord.TextChannel, nextcord.ForumChannel)) or channel.guild.id != guild.id:
            raise CoreError(503, 'discord_destination_unavailable')
        publication = await db.fetch_one(
            'SELECT * FROM marketplace_core_publications WHERE publication_key=$1', delivery['publication_key']
        )
        if publication and (publication['guild_id'], publication['channel_id']) != (guild.id, channel.id):
            raise CoreError(409, 'publication_identity_conflict')
        version = int(event['canonical_version'])
        remove = event['type'] == 'listing.unpublish' or not event.get('listing') or event['public_state'] != 'public'
        if event.get('expires_at') and datetime.fromisoformat(
            event['expires_at'].replace('Z', '+00:00')
        ) <= datetime.now(UTC):
            remove = True
        if publication and (publication['canonical_version'] >= version or publication['removed']):
            return
        binding = await self.sync.binding(guild.id, channel.id)
        if not remove and (
            not binding
            or not binding.get('publication_enabled')
            or not binding.get('public_syndication_enabled')
            or not await guild_modules_service.enabled(guild.id, 'marketplace')
        ):
            raise CoreError(403, 'publication_disabled')
        if publication:
            target = (
                guild.get_thread(publication['thread_id']) or await guild.fetch_channel(publication['thread_id'])
                if publication['thread_id']
                else channel
            )
            try:
                message = await target.fetch_message(publication['message_id'])
                if message.author.id != self.bot.user.id:
                    raise CoreError(409, 'publication_owner_conflict')
                if remove:
                    await message.delete()
                else:
                    await message.edit(embed=self._publication_embed(event), attachments=[])
            except nextcord.NotFound:
                if not remove:
                    raise CoreError(409, 'publication_missing') from None
            await db.execute(
                'UPDATE marketplace_core_publications SET canonical_version=$2,removed=$3 WHERE publication_key=$1',
                delivery['publication_key'],
                version,
                remove,
            )
            return
        if remove:
            return
        embed = self._publication_embed(event)
        listing = event['listing']
        file = None
        if listing['images']:
            asset = str(uuid.UUID(listing['images'][0]['asset_id']))
            stored = await self.sync.client.request('GET', '/v1/integrations/marketplace/media/' + asset, binary=True)
            file = stored.file()
            embed.set_image(url='attachment://' + file.filename)
        if isinstance(channel, nextcord.ForumChannel):
            tag_ids = {
                m['tag_id'] for m in binding.get('tag_categories', []) if m['category_id'] == listing['category_id']
            }
            tags = [tag for tag in channel.available_tags if str(tag.id) in tag_ids][:1]
            if channel.flags.require_tag and not tags:
                raise CoreError(422, 'publication_tag_required')
            result = await outbound.create_thread(
                channel,
                kind='marketplace_publish',
                name=listing['title'][:100],
                embed=embed,
                file=file,
                applied_tags=tags,
                dedupe_key=delivery['publication_key'],
            )
            if not result.ok or result.thread is None:
                raise CoreError(503, 'discord_delivery_failed')
            message_id, thread_id = result.thread.id, result.thread.id
        else:
            result = await outbound.send(
                channel, kind='marketplace_publish', embed=embed, file=file, dedupe_key=delivery['publication_key']
            )
            if not result.ok or result.message is None:
                raise CoreError(503, 'discord_delivery_failed')
            message_id, thread_id = result.message.id, None
        await db.execute(
            'INSERT INTO marketplace_core_publications(publication_key,guild_id,channel_id,message_id,thread_id,listing_id,canonical_version) '
            'VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT DO NOTHING',
            delivery['publication_key'],
            guild.id,
            channel.id,
            message_id,
            thread_id,
            uuid.UUID(event['listing_id']),
            version,
        )

    @staticmethod
    def _publication_embed(event):
        listing = event['listing']
        embed = nextcord.Embed(
            title=clip_text(listing['title'], 220),
            description=clip_text(listing['description_plaintext'], 3000),
            url='https://veka.gg/marketplace/' + str(uuid.UUID(event['listing_id'])),
        )
        price = listing['price']
        embed.add_field(
            name='Price',
            value=f'{Decimal(price["amount_minor"]) / 100} {price["currency"]}'
            if price['amount_minor'] is not None
            else 'Ask seller',
        )
        return embed


def setup(bot):
    bot.add_cog(Marketplace(bot))
