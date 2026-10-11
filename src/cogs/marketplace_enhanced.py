"""
Enhanced Marketplace Features
Search, notifications, and engagement features to keep users active
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import nextcord
from nextcord.ext import commands, tasks

from src.database.database import db, get_user
from src.services.marketplace_service import normalize_search_filters, validate_price
from src.utils.embed_limits import text_units
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.marketplace.fraud_detection import fraud_detector
from src.utils.outbound import outbound
from src.utils.safety import safe_send, safe_slash_command
from src.utils.security import sanitize

logger = logging.getLogger('VEKA.marketplace.enhanced')

LISTING_EXPIRY_DAYS = 30
LISTING_WARN_DAYS = 27
# A bump refreshes a listing, so age counts from the most recent of creation / bump.
_LISTING_AGE_SQL = 'COALESCE(GREATEST(l.created_at, l.last_bumped_at), l.created_at)'


class MarketplaceEnhanced(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_ready(self):
        for loop in (self.check_price_drops, self.check_expiring_listings):
            if not loop.is_running():
                loop.start()

    def cog_unload(self):
        self.check_price_drops.cancel()
        self.check_expiring_listings.cancel()

    # ==================== SLASH COMMANDS (delegated via /marketplace group) ====================

    async def search_slash(self, interaction: nextcord.Interaction, query: str):
        try:
            filters = self._parse_search_query(query)
            search_term = filters.get('term', '')
            listings = await self._run_search(filters)

            if not listings:
                embed = await info_embed(
                    title='No Results',
                    description='No items found matching your search.',
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            embed = await info_embed(
                title=f'🔍 Search Results ({len(listings)} items)',
                description=f'Query: **{search_term or "All items"}**',
                contributor_source=__name__,
                user=interaction.user,
            )

            for listing in listings[:10]:
                seller = interaction.guild.get_member(int(listing['discord_id']))
                seller_name = seller.display_name if seller else 'Unknown'

                value = (
                    f'💰 **${listing["price"]}** | {listing["emoji"]} {listing["category_name"]}\n'
                    f'👤 {seller_name} | ⭐ {listing["average_rating"] or "N/A"} | 📦 {listing["total_sales"] or 0} sales\n'
                    f'🆔 `{listing["id"]}` | 👁️ {listing["views"]} views'
                )
                embed.add_field(name=f'{listing["emoji"]} {listing["title"][:50]}', value=value, inline=False)

            if len(listings) > 10:
                embed.set_footer(text=f'Showing 10 of {len(listings)} results.')

            await safe_send(interaction, embed=embed, ephemeral=False)

        except ValueError as exc:
            embed = await error_embed('Invalid Search', str(exc), contributor_source=__name__, user=interaction.user)
            await safe_send(interaction, embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f'Search error: {str(e)}')
            embed = await error_embed(
                'Search Error', 'An error occurred while searching.', contributor_source=__name__, user=interaction.user
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    async def watch_slash(self, interaction: nextcord.Interaction, listing_id: str):
        try:
            user = await get_user(str(interaction.user.id))
            listing = await db.fetch_one('SELECT title, price FROM marketplace_listings WHERE id = $1', listing_id)

            if not listing:
                embed = await error_embed(
                    'Not Found', 'Listing not found.', contributor_source=__name__, user=interaction.user
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            await db.execute(
                'INSERT INTO marketplace_watchlist (user_id, listing_id) VALUES ($1, $2) ON CONFLICT DO NOTHING',
                user['id'],
                listing_id,
            )

            embed = await success_embed(
                title='Added to Watchlist',
                description=f"**{listing['title']}** added to your watchlist! You'll be notified of price changes.",
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'Watchlist error: {str(e)}')
            embed = await error_embed(
                'Watchlist Error', 'An error occurred.', contributor_source=__name__, user=interaction.user
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    async def unwatch_slash(self, interaction: nextcord.Interaction, listing_id: str):
        try:
            user = await get_user(str(interaction.user.id))
            await db.execute(
                'DELETE FROM marketplace_watchlist WHERE user_id = $1 AND listing_id = $2', user['id'], listing_id
            )

            embed = await success_embed(
                title='Removed',
                description='Item removed from your watchlist.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'Unwatch error: {str(e)}')
            embed = await error_embed(
                'Unwatch Error', 'An error occurred.', contributor_source=__name__, user=interaction.user
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    async def watchlist_slash(self, interaction: nextcord.Interaction):
        try:
            user = await get_user(str(interaction.user.id))

            items = await db.fetch_many(
                """SELECT l.*, c.name as category_name, c.emoji
                   FROM marketplace_watchlist w
                   JOIN marketplace_listings l ON w.listing_id = l.id
                   JOIN marketplace_categories c ON l.category_id = c.id
                   WHERE w.user_id = $1
                   ORDER BY w.created_at DESC""",
                user['id'],
            )

            if not items:
                embed = await info_embed(
                    title='Your Watchlist',
                    description="You're not watching any items. Use `/watch` to track items!",
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            embed = await info_embed(
                title='📋 Your Watchlist',
                description=f"You're tracking {len(items)} item(s)",
                contributor_source=__name__,
                user=interaction.user,
            )

            for item in items:
                status_emoji = '🟢' if item['status'] == 'active' else '🔴'
                value = f'💰 ${item["price"]} | {status_emoji} {item["status"]} | 👁️ {item["views"]} views'
                embed.add_field(name=f'{item["emoji"]} {item["title"][:50]}', value=value, inline=False)

            await safe_send(interaction, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'View watchlist error: {str(e)}')
            embed = await error_embed(
                'Watchlist Error', 'An error occurred.', contributor_source=__name__, user=interaction.user
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    async def offer_slash(self, interaction: nextcord.Interaction, listing_id: str, price: str, message: str = ''):
        try:
            buyer = await get_user(str(interaction.user.id))

            listing = await db.fetch_one(
                """SELECT l.*, u.discord_id as seller_discord_id
                   FROM marketplace_listings l
                   JOIN users u ON l.seller_id = u.id
                   WHERE l.id = $1 AND l.status = 'active'""",
                listing_id,
            )

            if not listing:
                embed = await error_embed(
                    'Not Found',
                    'Listing not found or no longer available.',
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            if str(interaction.user.id) == listing['seller_discord_id']:
                embed = await error_embed(
                    'Invalid Action',
                    "You can't make an offer on your own item!",
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            try:
                offered_price = validate_price(price)
            except ValueError as exc:
                embed = await error_embed('Invalid Price', str(exc), contributor_source=__name__, user=interaction.user)
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            if not listing['is_negotiable']:
                embed = await error_embed(
                    'Not Negotiable',
                    'This seller is not accepting offers on this item.',
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            is_clean, fraud_reason = await fraud_detector.check_offer(
                listing_id, buyer['id'], listing['seller_id'], Decimal(str(offered_price))
            )

            if not is_clean:
                embed = await error_embed(
                    'Offer Blocked', fraud_reason, contributor_source=__name__, user=interaction.user
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            expires = datetime.now(UTC) + timedelta(days=3)
            await db.execute(
                """INSERT INTO marketplace_offers
                   (listing_id, buyer_id, offered_price, message, expires_at)
                   VALUES ($1, $2, $3, $4, $5)""",
                listing_id,
                buyer['id'],
                offered_price,
                sanitize(message, max_length=500),
                expires,
            )

            embed = await success_embed(
                title='Offer Recorded',
                description=(
                    f'Your pending offer of **${offered_price}** is recorded for three days. '
                    'The seller can view it with `/marketplace myoffers`. '
                    'This does not create a purchase, payment or completed transaction; DM delivery is not guaranteed.'
                ),
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

            seller = interaction.guild.get_member(int(listing['seller_discord_id']))
            if seller:
                try:
                    seller_embed = await info_embed(
                        title='💰 New Offer Received!',
                        description=f'Someone offered **${offered_price}** for **{listing["title"]}**',
                        contributor_source=__name__,
                        user=interaction.user,
                    )
                    if message:
                        seller_embed.add_field(name='Message', value=message[:500], inline=False)
                    seller_embed.add_field(name='Original Price', value=f'${listing["price"]}', inline=True)
                    seller_embed.add_field(name='Expires', value='3 days', inline=True)
                    await outbound.dm(seller, kind='marketplace_offer', embed=seller_embed)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f'Offer error: {str(e)}')
            embed = await error_embed(
                'Offer Error',
                'An error occurred while making the offer.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    async def myoffers_slash(self, interaction: nextcord.Interaction):
        try:
            user = await get_user(str(interaction.user.id))

            received_offers = await db.fetch_many(
                """SELECT o.*, l.title, l.price as original_price, u.discord_id as buyer_discord_id
                   FROM marketplace_offers o
                   JOIN marketplace_listings l ON o.listing_id = l.id
                   JOIN users u ON o.buyer_id = u.id
                   WHERE l.seller_id = $1 AND o.status = 'pending' AND o.expires_at > NOW()
                   ORDER BY o.created_at DESC""",
                user['id'],
            )

            sent_offers = await db.fetch_many(
                """SELECT o.*, l.title, l.price as original_price
                   FROM marketplace_offers o
                   JOIN marketplace_listings l ON o.listing_id = l.id
                   WHERE o.buyer_id = $1 AND o.status = 'pending' AND o.expires_at > NOW()
                   ORDER BY o.created_at DESC""",
                user['id'],
            )

            embed = await info_embed(title='💰 Your Offers', contributor_source=__name__, user=interaction.user)

            if received_offers:
                offers_text = ''
                for offer in received_offers[:5]:
                    buyer = interaction.guild.get_member(int(offer['buyer_discord_id']))
                    buyer_name = buyer.display_name if buyer else 'Unknown'
                    offers_text += f'• **{offer["title"][:30]}**: ${offer["offered_price"]} (from {buyer_name})\n'
                embed.add_field(
                    name=f'📥 Received ({len(received_offers)})', value=offers_text or 'No pending offers', inline=False
                )

            if sent_offers:
                offers_text = ''
                for offer in sent_offers[:5]:
                    offers_text += f'• **{offer["title"][:30]}**: ${offer["offered_price"]}\n'
                embed.add_field(
                    name=f'📤 Sent ({len(sent_offers)})', value=offers_text or 'No pending offers', inline=False
                )

            if not received_offers and not sent_offers:
                embed.description = '📭 No pending offers.'

            await safe_send(interaction, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'View offers error: {str(e)}')
            embed = await error_embed(
                'Offers Error', 'An error occurred.', contributor_source=__name__, user=interaction.user
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='featured', description='View featured and trending listings')
    @safe_slash_command(requires_db=True)
    async def featured_slash(self, interaction: nextcord.Interaction):
        try:
            featured = await db.fetch_many(
                """SELECT l.*, u.discord_id, c.name as category_name, c.emoji,
                       s.average_rating, s.total_sales
                   FROM marketplace_listings l
                   JOIN users u ON l.seller_id = u.id
                   JOIN marketplace_categories c ON l.category_id = c.id
                   LEFT JOIN marketplace_seller_stats s ON l.seller_id = s.user_id
                   WHERE l.status = 'active'
                   AND l.views > 10
                   AND (s.average_rating IS NULL OR s.average_rating >= 4.0)
                   ORDER BY l.views DESC, l.created_at DESC
                   LIMIT 10"""
            )

            if not featured:
                embed = await info_embed(
                    title='No Featured Listings',
                    description='No featured listings yet. Be the first to post something amazing!',
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            embed = await info_embed(
                title='🔥 Featured & Trending',
                description='Popular items from trusted sellers',
                contributor_source=__name__,
                user=interaction.user,
            )

            for i, listing in enumerate(featured[:5], 1):
                seller = interaction.guild.get_member(int(listing['discord_id']))
                seller_name = seller.display_name if seller else 'Unknown'

                value = (
                    f'💰 ${listing["price"]} | 👁️ {listing["views"]} views\n'
                    f'👤 {seller_name} | ⭐ {listing["average_rating"] or "N/A"}\n'
                    f'🆔 `{listing["id"]}`'
                )
                embed.add_field(name=f'#{i} {listing["emoji"]} {listing["title"][:40]}', value=value, inline=False)

            await safe_send(interaction, embed=embed, ephemeral=False)

        except Exception as e:
            logger.error(f'Featured error: {str(e)}')
            embed = await error_embed(
                'Featured Error', 'An error occurred.', contributor_source=__name__, user=interaction.user
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='marketstats', description='View marketplace statistics')
    @safe_slash_command(requires_db=True)
    async def marketstats_slash(self, interaction: nextcord.Interaction):
        try:
            stats = await db.fetch_one(
                """SELECT
                   COUNT(*) FILTER (WHERE status = 'active') as active_listings,
                   COUNT(*) FILTER (WHERE status = 'sold') as sold_listings,
                   COUNT(DISTINCT seller_id) as active_sellers,
                   AVG(price) FILTER (WHERE status = 'active') as avg_price
                   FROM marketplace_listings"""
            )

            if stats is None:
                embed = await error_embed(
                    'Stats Error',
                    'Could not retrieve marketplace statistics.',
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            top_categories = await db.fetch_many(
                """SELECT c.name, c.emoji, COUNT(*) as count
                   FROM marketplace_listings l
                   JOIN marketplace_categories c ON l.category_id = c.id
                   WHERE l.status = 'active'
                   GROUP BY c.id
                   ORDER BY count DESC
                   LIMIT 5"""
            )

            top_sellers = await db.fetch_many(
                """SELECT u.discord_id, s.total_sales, s.average_rating
                   FROM marketplace_seller_stats s
                   JOIN users u ON s.user_id = u.id
                   ORDER BY s.total_sales DESC
                   LIMIT 5"""
            )

            embed = await info_embed(
                title='📊 Marketplace Statistics', contributor_source=__name__, user=interaction.user
            )

            embed.add_field(
                name='📦 Listings',
                value=f'Active: **{stats["active_listings"] or 0}**\nSold: **{stats["sold_listings"] or 0}**',
                inline=True,
            )

            embed.add_field(
                name='👥 Community',
                value=f'Active Sellers: **{stats["active_sellers"] or 0}**\nAvg Price: **${stats["avg_price"] or 0:.2f}**',
                inline=True,
            )

            if top_categories:
                cat_text = '\n'.join([f'{c["emoji"]} {c["name"]}: {c["count"]}' for c in top_categories])
                embed.add_field(name='📁 Top Categories', value=cat_text, inline=False)

            if top_sellers:
                seller_text = ''
                for i, seller in enumerate(top_sellers[:3], 1):
                    user = interaction.guild.get_member(int(seller['discord_id']))
                    name = user.display_name if user else 'Unknown'
                    seller_text += f'#{i} {name}: {seller["total_sales"]} sales\n'
                embed.add_field(name='🏆 Top Sellers', value=seller_text, inline=False)

            await safe_send(interaction, embed=embed, ephemeral=False)

        except Exception as e:
            logger.error(f'Stats error: {str(e)}')
            embed = await error_embed(
                'Stats Error', 'An error occurred.', contributor_source=__name__, user=interaction.user
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    # ==================== SHARED LOGIC ====================

    def _parse_search_query(self, query: str) -> dict:
        if not query.strip() or text_units(query) > 1000:
            raise ValueError('Search query must be 1–1000 characters.')
        filters = {}
        parts = query.split('|')
        if parts:
            filters['term'] = parts[0].strip()
        for part in parts[1:]:
            part = part.strip()
            if ':' in part:
                key, value = part.split(':', 1)
                key = key.strip().lower()
                if key in filters:
                    raise ValueError(f'Duplicate search filter: {key}.')
                filters[key] = value.strip()
            else:
                raise ValueError('Use filter:value after each | separator.')
        return normalize_search_filters(filters)

    async def _run_search(self, filters: dict) -> list[dict]:
        filters = normalize_search_filters(filters)
        search_term = filters.get('term', '')

        sql = """SELECT l.*, u.discord_id, c.name as category_name, c.emoji,
                        s.average_rating, s.total_sales
                 FROM marketplace_listings l
                 JOIN users u ON l.seller_id = u.id
                 JOIN marketplace_categories c ON l.category_id = c.id
                 LEFT JOIN marketplace_seller_stats s ON l.seller_id = s.user_id
                 WHERE l.status = 'active' AND l.is_expired = FALSE"""
        params = []
        param_count = 0

        if search_term:
            param_count += 1
            sql += f" AND (to_tsvector('english', l.title) @@ plainto_tsquery('english', ${param_count})"
            sql += f" OR to_tsvector('english', l.description) @@ plainto_tsquery('english', ${param_count})"
            sql += f' OR l.tags && ARRAY[${param_count}])'
            params.append(search_term)

        if 'min_price' in filters:
            param_count += 1
            sql += f' AND l.price >= ${param_count}'
            params.append(Decimal(filters['min_price']))

        if 'max_price' in filters:
            param_count += 1
            sql += f' AND l.price <= ${param_count}'
            params.append(Decimal(filters['max_price']))

        if 'condition' in filters:
            param_count += 1
            sql += f' AND l.condition = ${param_count}'
            params.append(filters['condition'])

        if 'category' in filters:
            param_count += 1
            sql += f' AND LOWER(c.name) = LOWER(${param_count})'
            params.append(filters['category'])

        if 'min_rating' in filters:
            param_count += 1
            sql += f' AND s.average_rating >= ${param_count}'
            params.append(filters['min_rating'])

        sort = filters.get('sort', 'newest')
        if sort == 'price_low':
            sql += ' ORDER BY l.price ASC NULLS LAST, l.id DESC'
        elif sort == 'price_high':
            sql += ' ORDER BY l.price DESC NULLS LAST, l.id DESC'
        elif sort == 'popular':
            sql += ' ORDER BY l.views DESC, l.id DESC'
        else:
            sql += ' ORDER BY COALESCE(GREATEST(l.created_at, l.last_bumped_at), l.created_at) DESC, l.id DESC'

        sql += ' LIMIT 20'
        return await db.fetch_many(sql, *params)

    # ==================== BACKGROUND TASKS ====================

    async def _notify_sellers(self, listings, *, expired: bool):
        """One bounded digest per seller; never try users absent from all bot guilds."""
        by_seller: dict[int, list] = {}
        for listing in listings:
            by_seller.setdefault(int(listing['discord_id']), []).append(listing)
        failures = 0
        for user_id, items in list(by_seller.items())[:25]:
            seller = next((g.get_member(user_id) for g in self.bot.guilds if g.get_member(user_id)), None)
            if seller is None:
                continue
            embed = await info_embed(
                title='Listings Expired' if expired else 'Listings Expiring Soon',
                description='Use `/marketplace bump` to refresh a listing or `/marketplace withdraw` to remove it.',
                contributor_source=__name__,
                user=seller,
            )
            for item in items[:10]:
                embed.add_field(name=item['title'][:100], value=f'Listing ID: `{item["id"]}`', inline=False)
            if len(items) > 10:
                embed.set_footer(text=f'{len(items)} listings affected; showing the first 10.')
            try:
                outcome = await outbound.dm(seller, kind='marketplace_expiry', embed=embed)
                failures = 0 if outcome.ok else failures + 1
                if failures >= 3:
                    break
            except (nextcord.Forbidden, nextcord.HTTPException):
                failures += 1
                if failures >= 3:
                    break
            await asyncio.sleep(5)

    @tasks.loop(hours=6)
    async def check_price_drops(self):
        """Warn sellers once, a few days before a listing expires (age counts from the last bump)."""
        try:
            expiring = await db.fetch_many(
                f"""WITH candidates AS (
                       SELECT l.id FROM marketplace_listings l
                       WHERE l.status = 'active' AND l.is_expired = FALSE
                         AND {_LISTING_AGE_SQL} < NOW() - INTERVAL '{LISTING_WARN_DAYS} days'
                         AND {_LISTING_AGE_SQL} >= NOW() - INTERVAL '{LISTING_EXPIRY_DAYS} days'
                         AND (l.expiry_warned_at IS NULL OR l.expiry_warned_at < {_LISTING_AGE_SQL})
                       ORDER BY l.created_at LIMIT 25
                   ) UPDATE marketplace_listings l SET expiry_warned_at = NOW()
                   FROM users u WHERE l.seller_id = u.id AND l.id IN (SELECT id FROM candidates)
                     AND l.status = 'active' AND l.is_expired = FALSE
                     AND {_LISTING_AGE_SQL} < NOW() - INTERVAL '{LISTING_WARN_DAYS} days'
                     AND (l.expiry_warned_at IS NULL OR l.expiry_warned_at < {_LISTING_AGE_SQL})
                   RETURNING l.id, l.title, u.discord_id"""
            )

            await self._notify_sellers(expiring, expired=False)

        except Exception as e:
            logger.error(f'Listing expiry warning error: {str(e)}')

    @tasks.loop(hours=24)
    async def check_expiring_listings(self):
        try:
            # Flag listings older than 30 days as expired
            expired_rows = await db.fetch_many(
                f"""UPDATE marketplace_listings l SET is_expired = TRUE
                   FROM users u
                   WHERE l.seller_id = u.id AND l.status = 'active' AND l.is_expired = FALSE
                     AND {_LISTING_AGE_SQL} < NOW() - INTERVAL '{LISTING_EXPIRY_DAYS} days'
                   RETURNING l.id, l.title, u.discord_id"""
            )

            if expired_rows:
                await self._notify_sellers(expired_rows, expired=True)
                logger.info('Flagged %d expired listings', len(expired_rows))

        except Exception as e:
            logger.error(f'Expiring listings error: {str(e)}')

    @check_price_drops.before_loop
    async def before_price_drops(self):
        await self.bot.wait_until_ready()

    @check_expiring_listings.before_loop
    async def before_expiring_listings(self):
        # Previously missing: the first run fired at import time, before the DB connected.
        await self.bot.wait_until_ready()


def setup(bot):
    bot.add_cog(MarketplaceEnhanced(bot))
