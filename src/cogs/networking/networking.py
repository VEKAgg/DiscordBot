from __future__ import annotations

import logging
import re
from collections.abc import Callable
from urllib.parse import urlparse

import nextcord
from nextcord.ext import commands

from src.database.database import db
from src.services.networking_service import NetworkingService, normalize_skills
from src.utils.embed_limits import bounded_items, clip_text
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.outbound import outbound
from src.utils.safety import safe_command, safe_send, safe_slash_command

logger = logging.getLogger('VEKA.networking')


class ConnectionRequestView(nextcord.ui.View):
    """Searchable member picker for a connection request.

    Uses Discord's native user select, which searches the whole server (the previous static
    dropdown only ever listed the first 25 members — audit M-11).
    """

    def __init__(
        self,
        guild: nextcord.Guild,
        requester_id: str,
        message: str,
        svc: NetworkingService,
        response_factory: Callable[..., ConnectionResponseView] = None,
    ):
        super().__init__(timeout=120)
        self.guild = guild
        self.requester_id = requester_id
        self.message = message
        self.svc = svc
        self.response_factory = response_factory or ConnectionResponseView

        select: nextcord.ui.UserSelect = nextcord.ui.UserSelect(placeholder='Search for a member to connect with...')
        select.callback = self._select_callback  # type: ignore[method-assign]
        self.select = select
        self.add_item(select)

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        from src.services.guild_modules_service import guild_modules_service

        if interaction.guild and not await guild_modules_service.enabled(interaction.guild.id, 'networking'):
            await interaction.response.send_message(
                'This feature is turned off in this server by its admins.', ephemeral=True
            )
            return False
        # The prefix variant posts this picker publicly; only the invoker may use it, otherwise
        # another member could send requests in the invoker's name.
        if interaction.user is None or str(interaction.user.id) != self.requester_id:
            await interaction.response.send_message(
                'Only the member who ran the command can use this picker.', ephemeral=True
            )
            return False
        return True

    async def _select_callback(self, interaction: nextcord.Interaction):
        chosen = self.select.values.members or self.select.values.users
        target = chosen[0] if chosen else None
        selected_member = self.guild.get_member(target.id) if target else None
        if selected_member is None or selected_member.bot or str(selected_member.id) == self.requester_id:
            embed = await error_embed(
                title='Invalid Selection',
                description='Pick another (non-bot) member of this server.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await interaction.response.edit_message(embed=embed, view=self)
            return
        selected_id = str(selected_member.id)

        try:
            request_id = await self.svc.create_request(self.requester_id, selected_id, self.message)
            embed = await success_embed(
                title='Connection Request Recorded',
                description=f'Your pending request to **{selected_member.display_name}** is recorded. DM delivery is not guaranteed.',
                contributor_source=__name__,
                user=interaction.user,
            )
            if self.message:
                embed.add_field(name='Message', value=self.message, inline=False)
            await interaction.response.edit_message(embed=embed, view=None)

            notify = await info_embed(
                title='New Connection Request',
                description=f'{interaction.user.mention} would like to connect with you.',
                contributor_source=__name__,
                user=selected_member,
            )
            if self.message:
                notify.add_field(name='Message', value=self.message, inline=False)
            view = self.response_factory(
                request_id=request_id,
                requester_id=self.requester_id,
                recipient_id=selected_id,
                requester_name=interaction.user.display_name,
                svc=self.svc,
            )
            try:
                outcome = await outbound.dm(selected_member, kind='connection_request', embed=notify, view=view)
                if not outcome.ok:
                    view.stop()
            except BaseException:
                view.stop()
                raise
        except ValueError as exc:
            embed = await error_embed(
                title='Unable to Send Request',
                description=str(exc),
                contributor_source=__name__,
                user=interaction.user,
            )
            await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        pass


async def _fetch_user(client, user_id: str) -> nextcord.User | None:
    try:
        return client.get_user(int(user_id)) or await client.fetch_user(int(user_id))
    except (nextcord.NotFound, nextcord.HTTPException, ValueError):
        return None


class ConnectionResponseView(nextcord.ui.View):
    """Accept/Decline buttons sent via DM for a connection request."""

    def __init__(
        self,
        request_id: int,
        requester_id: str,
        recipient_id: str,
        requester_name: str,
        svc: NetworkingService,
        on_finish: Callable[[ConnectionResponseView], None] | None = None,
    ):
        super().__init__(timeout=None)
        self.on_finish = on_finish
        self.request_id = request_id
        self.requester_id = requester_id
        self.recipient_id = recipient_id
        self.requester_name = requester_name
        self.svc = svc
        for button in self.children:
            if isinstance(button, nextcord.ui.Button):
                action = 'accept' if button.label == 'Accept' else 'decline'
                button.custom_id = f'connection:{request_id}:{action}'

    def stop(self) -> None:
        super().stop()
        callback, self.on_finish = self.on_finish, None
        if callback is not None:
            callback(self)

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if str(interaction.user.id) != self.recipient_id:
            await interaction.response.send_message('Only the recipient can respond to this request.', ephemeral=True)
            return False
        return True

    @nextcord.ui.button(
        label='Accept', style=nextcord.ButtonStyle.success, emoji='\u2705', custom_id='connection:accept'
    )
    async def accept_button(self, _button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.defer()
        try:
            if not await self.svc.respond_request(self.request_id, str(interaction.user.id), accept=True):
                self.stop()
                await interaction.edit_original_message(content='This request has already been processed.', view=None)
                return
            self.stop()

            embed = await success_embed(
                title='Connection Accepted',
                description=f'You are now connected with **{self.requester_name}**.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await interaction.edit_original_message(embed=embed, view=None)

            # Buttons are clicked in DMs, where interaction.guild is None — look the requester up globally.
            requester = await _fetch_user(interaction.client, self.requester_id)
            if requester:
                try:
                    notify = await success_embed(
                        title='Connection Accepted',
                        description=f'{interaction.user.mention} accepted your connection request.',
                        contributor_source=__name__,
                        user=requester,
                    )
                    await outbound.dm(requester, kind='connection_accepted', embed=notify)
                except nextcord.Forbidden:
                    pass
        except Exception as exc:
            logger.error('Failed to accept connection: %s', exc, exc_info=True)
            if not self.is_finished():
                await interaction.edit_original_message(
                    content='Unable to process this request right now. Please try again.', view=self
                )

    @nextcord.ui.button(
        label='Decline', style=nextcord.ButtonStyle.danger, emoji='\u274c', custom_id='connection:decline'
    )
    async def decline_button(self, _button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.defer()
        try:
            if not await self.svc.respond_request(self.request_id, str(interaction.user.id), accept=False):
                self.stop()
                await interaction.edit_original_message(content='This request has already been processed.', view=None)
                return
            self.stop()

            embed = await error_embed(
                title='Connection Declined',
                description=f'You declined the request from **{self.requester_name}**.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await interaction.edit_original_message(embed=embed, view=None)

            # Buttons are clicked in DMs, where interaction.guild is None — look the requester up globally.
            requester = await _fetch_user(interaction.client, self.requester_id)
            if requester:
                try:
                    notify = await error_embed(
                        title='Connection Declined',
                        description=f'{interaction.user.mention} declined your connection request.',
                        contributor_source=__name__,
                        user=requester,
                    )
                    await outbound.dm(requester, kind='connection_declined', embed=notify)
                except nextcord.Forbidden:
                    pass
        except Exception as exc:
            logger.error('Failed to decline connection: %s', exc, exc_info=True)
            if not self.is_finished():
                await interaction.edit_original_message(
                    content='Unable to process this request right now. Please try again.', view=self
                )


class Networking(commands.Cog):
    @nextcord.slash_command(
        name='profile',
        description='Professional profile commands',
    )
    async def profile(self, interaction: nextcord.Interaction):
        embed = await info_embed(
            title='Profile Commands',
            description=(
                '**Available subcommands:**\n\n'
                '\u2022 `/profile setup` \u2014 Create or update your profile\n'
                '\u2022 `/profile edit` \u2014 Edit profile fields\n'
                '\u2022 `/profile view` \u2014 View a profile'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(
        name='connect',
        description='Connection request commands',
    )
    async def connect(self, interaction: nextcord.Interaction):
        embed = await info_embed(
            title='Connect Commands',
            description=(
                '**Available subcommands:**\n\n'
                '\u2022 `/connect request` \u2014 Send a connection request\n'
                '\u2022 `/connect list` \u2014 View pending requests'
            ),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    def __init__(self, bot):
        self.bot = bot
        self.svc = NetworkingService()
        self._response_views: dict[int, ConnectionResponseView] = {}
        self._unloaded = False

    def _forget_response_view(self, view: ConnectionResponseView) -> None:
        if self._response_views.get(view.request_id) is view:
            self._response_views.pop(view.request_id)

    def _make_response_view(
        self, request_id: int, requester_id: str, recipient_id: str, requester_name: str, svc: NetworkingService
    ) -> ConnectionResponseView:
        if self._unloaded:
            raise RuntimeError('Networking cog was unloaded; retry the command.')
        view = ConnectionResponseView(
            request_id, requester_id, recipient_id, requester_name, svc, on_finish=self._forget_response_view
        )
        previous = self._response_views.get(view.request_id)
        if previous is not None:
            previous.stop()
        self.bot.add_view(view)
        self._response_views[view.request_id] = view
        return view

    async def cog_ready(self):
        existing = dict(self._response_views)
        seen: set[int] = set()
        after_id = 0
        while not self._unloaded:
            requests = await self.svc.get_pending_requests(after_id=after_id)
            if self._unloaded:
                return
            if not requests:
                break
            for request in requests:
                request_id = request['id']
                seen.add(request_id)
                if request_id not in self._response_views:
                    self._make_response_view(
                        request_id,
                        request['requester_discord_id'],
                        request['recipient_discord_id'],
                        f'Member {request["requester_discord_id"]}',
                        self.svc,
                    )
            after_id = requests[-1]['id']
        # Do not prune a newly sent view that appeared after reconciliation started.
        for request_id, view in existing.items():
            if request_id not in seen and self._response_views.get(request_id) is view:
                view.stop()

    def cog_unload(self):
        self._unloaded = True
        for view in list(self._response_views.values()):
            view.stop()
        self._response_views.clear()

    def _normalize_links(self, links: str | None) -> str | None:
        if not links:
            return None

        parts = [item.strip() for item in re.split(r'[\n,;]+', links) if item.strip()]
        normalized = []
        for raw in parts:
            url_text = raw
            if not re.match(r'https?://', raw, re.I):
                url_text = f'https://{raw}'

            parsed = urlparse(url_text)
            if parsed.scheme.lower() not in {'http', 'https'} or not parsed.netloc:
                raise ValueError(f'Invalid link provided: {raw}')

            normalized.append(url_text)

        if len(normalized) > 5:
            raise ValueError('You may provide up to 5 links.')

        return '\n'.join(normalized)

    def _links_display(self, links: str | None) -> str:
        if not links:
            return 'Not set'
        return '\n'.join(f'<{link}>' for link in links.splitlines())

    async def _format_profile(
        self,
        target: nextcord.Member,
        profile: dict,
        user: nextcord.Member,
        viewer: nextcord.Member | None = None,
    ) -> nextcord.Embed:
        embed = await info_embed(
            title=f"{clip_text(target.display_name, 100)}'s Professional Profile",
            description='A concise overview of community networking details.',
            contributor_source=__name__,
            user=user,
        )
        embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
        embed.add_field(name='Title', value=clip_text(profile.get('title') or 'Not set', 200), inline=False)
        skills = profile.get('skills') or []
        parts = skills.split(',') if isinstance(skills, str) else skills
        skills_text = bounded_items([clip_text(skill, 64) for skill in parts if skill], 600) if parts else 'Not set'
        embed.add_field(name='Skills', value=skills_text, inline=False)
        embed.add_field(name='Timezone', value=clip_text(profile.get('timezone') or 'Not set', 64), inline=True)
        embed.add_field(
            name='About',
            value=clip_text(profile.get('bio') or profile.get('experience') or 'Not set', 900),
            inline=False,
        )
        embed.add_field(name='Looking For', value=clip_text(profile.get('looking_for') or 'Not set', 600), inline=False)
        embed.add_field(name='Links', value=clip_text(self._links_display(profile.get('links')), 900), inline=False)

        conn_count = await self.svc.get_connection_count(str(target.id))
        embed.add_field(name='Connections', value=str(conn_count), inline=True)

        stats = await self.svc.get_seller_stats(str(target.id))
        if stats and stats['review_count']:
            rep_text = (
                f'\u2b50 {stats["average_rating"]:.1f}/5 ({stats["review_count"]} reviews)\n'
                f'\U0001f4e6 {stats["total_sales"]} sales'
            )
        else:
            rep_text = 'No reviews yet'
        embed.add_field(name='Reputation', value=rep_text, inline=True)

        if viewer and viewer != target:
            mutual = await self.svc.get_mutual_connections(str(viewer.id), str(target.id))
            if mutual:
                mutual_names = []
                for mid in mutual[:3]:
                    member = viewer.guild.get_member(int(mid)) if viewer.guild else None
                    mutual_names.append(member.display_name if member else f'User {mid}')
                mutual_text = '\n'.join(f'\u2022 {name}' for name in mutual_names)
                if len(mutual) > 3:
                    mutual_text += f'\n...and {len(mutual) - 3} more'
            else:
                mutual_text = 'None'
            embed.add_field(name='Mutual Connections', value=clip_text(mutual_text, 300), inline=False)

        embed.set_footer(text=f'Last updated: {profile.get("last_updated", "Never")}')
        return embed

    async def _build_profile_data(self, existing: dict | None, values: dict) -> dict:
        profile_data = {}
        for field in ['title', 'skills', 'bio', 'links', 'looking_for', 'timezone']:
            if values.get(field) is not None:
                profile_data[field] = values[field]
            elif existing:
                profile_data[field] = existing.get(field)
        return profile_data

    async def _send_profile_missing(self, interaction: nextcord.Interaction, target: nextcord.Member):
        message = (
            'You have not set up a profile yet. Use `/profile setup` to create one.'
            if target == interaction.user
            else f'{target.display_name} has not set up a profile yet.'
        )
        embed = await error_embed(
            title='Profile Not Found',
            description=message,
            contributor_source=__name__,
            user=interaction.user,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @profile.subcommand(name='setup', description='Create your professional profile')
    @safe_slash_command(requires_db=True)
    async def profile_setup(
        self,
        interaction: nextcord.Interaction,
        title: str,
        skills: str | None = None,
        bio: str | None = None,
        links: str | None = None,
        looking_for: str | None = None,
    ):
        """Create or update your professional profile with core fields."""
        try:
            normalized_links = self._normalize_links(links)
            profile_data = {
                'title': title.strip(),
                'skills': skills.strip() if skills else None,
                'bio': bio.strip() if bio else None,
                'links': normalized_links,
                'looking_for': looking_for.strip() if looking_for else None,
            }
            await self.svc.upsert_profile(str(interaction.user.id), profile_data)
            embed = await success_embed(
                title='Profile Saved',
                description='Your professional profile is now up to date.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
        except ValueError as exc:
            embed = await error_embed(
                title='Invalid Profile Data',
                description=str(exc),
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    @profile.subcommand(name='edit', description='Edit your existing profile')
    @safe_slash_command(requires_db=True)
    async def profile_edit(
        self,
        interaction: nextcord.Interaction,
        title: str | None = None,
        skills: str | None = None,
        bio: str | None = None,
        links: str | None = None,
        looking_for: str | None = None,
    ):
        """Update profile fields while preserving existing values."""
        if not any([title, skills, bio, links, looking_for]):
            embed = await error_embed(
                title='Nothing to Update',
                description='Provide at least one field to edit: title, skills, bio, links, or looking_for.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        try:
            existing = await self.svc.get_profile(str(interaction.user.id))
            normalized_links = self._normalize_links(links) if links is not None else None
            updates = {
                'title': title.strip() if title else None,
                'skills': skills.strip() if skills else None,
                'bio': bio.strip() if bio else None,
                'links': normalized_links,
                'looking_for': looking_for.strip() if looking_for else None,
            }
            profile_data = await self._build_profile_data(existing, updates)
            if not profile_data.get('title'):
                raise ValueError('A title is required for your profile.')

            await self.svc.upsert_profile(str(interaction.user.id), profile_data)
            embed = await success_embed(
                title='Profile Updated',
                description='Your profile changes have been saved.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
        except ValueError as exc:
            embed = await error_embed(
                title='Invalid Profile Data',
                description=str(exc),
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    @profile.subcommand(name='view', description='View a profile')
    @safe_slash_command(requires_db=True)
    async def profile_view(
        self,
        interaction: nextcord.Interaction,
        member: nextcord.Member | None = None,
    ):
        """View your or another member's profile."""
        target = member or interaction.user
        profile = await self.svc.get_profile(str(target.id))
        if not profile:
            await self._send_profile_missing(interaction, target)  # type: ignore[arg-type]
            return

        embed = await self._format_profile(
            target,  # type: ignore[arg-type]
            profile,
            user=interaction.user,  # type: ignore[arg-type]
            viewer=interaction.user,  # type: ignore[arg-type]
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @connect.subcommand(name='request', description='Send a connection request')
    @safe_slash_command(requires_db=True)
    async def connect_request(
        self,
        interaction: nextcord.Interaction,
        message: str | None = None,
    ):
        """Send a connection request — pick a user from the dropdown."""
        if interaction.guild is None:
            embed = await error_embed(
                'Server Only',
                'Start connection requests in a server.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            view = ConnectionRequestView(
                interaction.guild, str(interaction.user.id), message or '', self.svc, self._make_response_view
            )
            embed = await info_embed(
                title='Select a User',
                description='Choose the member you want to connect with from the dropdown below.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as exc:
            logger.error('Failed to start connection request: %s', exc, exc_info=True)
            embed = await error_embed(
                title='Error',
                description='Failed to load member list.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @connect.subcommand(name='list', description='List your connection requests and accepted connections')
    @safe_slash_command(requires_db=True)
    async def connect_list(self, interaction: nextcord.Interaction):
        """View pending incoming/outgoing requests and accepted connections."""
        requests = await self.svc.get_requests_for_user(str(interaction.user.id))
        connections = await self.svc.get_connections(str(interaction.user.id))

        pending_incoming = [
            r for r in requests if r['recipient_discord_id'] == str(interaction.user.id) and r['status'] == 'pending'
        ]
        pending_outgoing = [
            r for r in requests if r['requester_discord_id'] == str(interaction.user.id) and r['status'] == 'pending'
        ]

        embed = await info_embed(
            title='Connection Status',
            description='Overview of your pending and accepted networking connections.',
            contributor_source=__name__,
            user=interaction.user,
        )

        if pending_incoming:
            incoming_text = '\n'.join(
                f'• <@{req["requester_discord_id"]}> — {req["message"] or "No message"}'
                for req in pending_incoming[:10]
            )
        else:
            incoming_text = 'No pending incoming requests.'
        embed.add_field(name='Pending Incoming', value=incoming_text, inline=False)

        if pending_outgoing:
            outgoing_text = '\n'.join(
                f'• <@{req["recipient_discord_id"]}> — {req["message"] or "No message"}'
                for req in pending_outgoing[:10]
            )
        else:
            outgoing_text = 'No pending outgoing requests.'
        embed.add_field(name='Pending Outgoing', value=outgoing_text, inline=False)

        if connections:
            connected_text = '\n'.join(
                f'• <@{conn["user1_discord_id"] if conn["user1_discord_id"] != str(interaction.user.id) else conn["user2_discord_id"]}> — connected {conn.get("connected_at", "Unknown")}'
                for conn in connections[:10]
            )
        else:
            connected_text = 'No accepted connections yet.'
        embed.add_field(name='Accepted Connections', value=connected_text, inline=False)

        await safe_send(interaction, embed=embed, ephemeral=True)

    # ==================== /profile set — Granular Subcommands ====================

    @profile.subcommand(name='set', description='Set a specific profile field')
    @safe_slash_command(requires_db=True)
    async def profile_set(
        self,
        interaction: nextcord.Interaction,
        field: str = nextcord.SlashOption(
            name='field',
            description='Which field to set',
            choices={'Bio': 'bio', 'Links': 'links', 'Skills': 'skills', 'Timezone': 'timezone'},
        ),
        value: str = nextcord.SlashOption(name='value', description='Value to set'),
    ):
        """Set a single profile field (bio, links, skills, or timezone)."""
        try:
            existing = await self.svc.get_profile(str(interaction.user.id))
            updates: dict[str, object] = {}

            if field == 'bio':
                updates['bio'] = value.strip()[:1000]
            elif field == 'links':
                updates['links'] = self._normalize_links(value)
            elif field == 'skills':
                updates['skills'] = normalize_skills(value)
            elif field == 'timezone':
                updates['timezone'] = value.strip()[:64]

            # Preserve existing fields
            profile_data: dict[str, object] = {}
            for f in ['title', 'skills', 'bio', 'links', 'looking_for', 'timezone']:
                if f in updates:
                    profile_data[f] = updates[f]
                elif existing:
                    profile_data[f] = existing.get(f)

            if not profile_data.get('title') and existing:
                profile_data['title'] = existing.get('title')

            await self.svc.upsert_profile(str(interaction.user.id), profile_data)
            embed = await success_embed(
                title='Profile Updated',
                description=f'**{field.title()}** has been updated.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
        except ValueError as exc:
            embed = await error_embed(
                title='Update Failed',
                description=str(exc),
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    # ==================== /directory — Member Search ====================

    @nextcord.slash_command(name='directory', description='Search the member directory')
    @safe_slash_command(requires_db=True)
    async def directory_group(self, interaction: nextcord.Interaction):
        embed = await info_embed(
            title='Directory Commands',
            description=('**Available subcommands:**\n\n• `/directory search` — Find members by skill or timezone'),
            contributor_source=__name__,
            user=interaction.user,
            guild=interaction.guild,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

    @directory_group.subcommand(name='search', description='Search members by skill or timezone')
    @safe_slash_command(requires_db=True)
    async def directory_search(
        self,
        interaction: nextcord.Interaction,
        skill: str = nextcord.SlashOption(name='skill', description='Skill to search for', required=False),
        timezone: str = nextcord.SlashOption(
            name='timezone', description='Timezone to search for (e.g. UTC, EST)', required=False
        ),
    ):
        if not skill and not timezone:
            embed = await error_embed(
                'Missing Filter',
                'Provide at least one filter: `skill` or `timezone`.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            if skill:
                # Search for profiles where skills array contains the skill (case-insensitive)
                rows = await db.fetch(
                    """SELECT p.user_id, p.title, p.skills, p.bio, u.discord_id
                       FROM profiles p
                       JOIN users u ON p.user_id = u.id
                       WHERE EXISTS (
                           SELECT 1 FROM unnest(p.skills) AS s
                           WHERE LOWER(s) = LOWER($1)
                       )
                       ORDER BY p.last_updated DESC
                       LIMIT 25""",
                    skill,
                )
            else:
                # Search by timezone
                rows = await db.fetch(
                    """SELECT p.user_id, p.title, p.skills, p.bio, p.timezone, u.discord_id
                       FROM profiles p
                       JOIN users u ON p.user_id = u.id
                       WHERE LOWER(p.timezone) = LOWER($1)
                       ORDER BY p.last_updated DESC
                       LIMIT 25""",
                    timezone,
                )

            if not rows:
                embed = await info_embed(
                    title='No Results',
                    description=f'No members found matching **{skill or timezone}**.',
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            embed = await info_embed(
                title=f'Directory: {skill or timezone}',
                description=f'{len(rows)} member{"s" if len(rows) != 1 else ""} found.',
                contributor_source=__name__,
                user=interaction.user,
            )

            for row in rows[:10]:
                member = interaction.guild.get_member(int(row['discord_id'])) if interaction.guild else None
                name = member.display_name if member else f'User {row["discord_id"]}'
                skills = row.get('skills') or []
                if isinstance(skills, str):
                    skills = [s.strip() for s in skills.split(',') if s.strip()]
                skills_text = ', '.join(skills[:5]) if skills else 'None'
                bio_text = (row.get('bio') or 'No bio')[:80]
                embed.add_field(
                    name=name,
                    value=f'Title: {row.get("title") or "N/A"}\nSkills: {skills_text}\nBio: {bio_text}',
                    inline=False,
                )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error('Directory search error: %s', e, exc_info=True)
            embed = await error_embed(
                'Search Error',
                'An error occurred while searching the directory.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.command(name='profile', description='View a professional profile')
    @safe_command(requires_db=True)
    async def profile_fallback(self, ctx, member: nextcord.Member = None):
        target = member or ctx.author
        profile = await self.svc.get_profile(str(target.id))
        if not profile:
            msg = (
                'You have not set up a profile yet. Use `!profile setup` to create one.'
                if target == ctx.author
                else f'{target.display_name} has not set up a profile yet.'
            )
            embed = await error_embed(
                title='Profile Not Found',
                description=msg,
                contributor_source=__name__,
                user=ctx.author,
            )
        else:
            embed = await self._format_profile(target, profile, user=ctx.author, viewer=ctx.author)
        await ctx.send(embed=embed)

    @commands.command(name='setupprofile', description='Set up your professional profile')
    @safe_command(requires_db=True)
    async def setupprofile_fallback(self, ctx):
        await ctx.send('Use `/profile setup` to create your profile. Slash commands provide the best experience.')

    @commands.command(name='connect', description='Send a connection request')
    @safe_command(requires_db=True)
    async def connect_fallback(self, ctx, member: nextcord.Member = None, *, message: str = None):
        if ctx.guild is None:
            embed = await error_embed(
                'Server Only', 'Start connection requests in a server.', contributor_source=__name__, user=ctx.author
            )
            await safe_send(ctx, embed=embed)
            return
        if not member:
            view = ConnectionRequestView(
                ctx.guild, str(ctx.author.id), message or '', self.svc, self._make_response_view
            )
            embed = await info_embed(
                title='Select a User',
                description='Choose the member you want to connect with from the dropdown below.',
                contributor_source=__name__,
                user=ctx.author,
            )
            await ctx.send(embed=embed, view=view)
            return
        try:
            if member.bot:
                raise ValueError('Pick another (non-bot) member of this server.')
            request_id = await self.svc.create_request(str(ctx.author.id), str(member.id), message or '')
            embed = await success_embed(
                title='Connection Request Recorded',
                description=f'Your pending request to {member.display_name} is recorded. DM delivery is not guaranteed.',
                contributor_source=__name__,
                user=ctx.author,
            )
            if message:
                embed.add_field(name='Message', value=message, inline=False)
            await ctx.send(embed=embed)

            notify = await info_embed(
                title='New Connection Request',
                description=f'{ctx.author.mention} would like to connect with you.',
                contributor_source=__name__,
                user=member,
            )
            if message:
                notify.add_field(name='Message', value=message, inline=False)
            response_view = self._make_response_view(
                request_id=request_id,
                requester_id=str(ctx.author.id),
                recipient_id=str(member.id),
                requester_name=ctx.author.display_name,
                svc=self.svc,
            )
            try:
                outcome = await outbound.dm(member, kind='connection_request', embed=notify, view=response_view)
                if not outcome.ok:
                    response_view.stop()
            except BaseException:
                response_view.stop()
                raise
        except ValueError as exc:
            embed = await error_embed(
                title='Unable to Send Request',
                description=str(exc),
                contributor_source=__name__,
                user=ctx.author,
            )
            await ctx.send(embed=embed)

    @commands.command(name='connections', description='View your connections')
    @safe_command(requires_db=True)
    async def connections_fallback(self, ctx):
        connections = await self.svc.get_connections(str(ctx.author.id))
        if not connections:
            embed = await info_embed(
                title='Your Connections',
                description='You have no connections yet. Use `/connect request` to reach out to someone.',
                contributor_source=__name__,
                user=ctx.author,
            )
            await ctx.send(embed=embed)
            return
        embed = await info_embed(
            title='Your Connections',
            description=f'You have {len(connections)} accepted connection(s).',
            contributor_source=__name__,
            user=ctx.author,
        )
        for conn in connections:
            other_id = (
                conn['user2_discord_id'] if conn['user1_discord_id'] == str(ctx.author.id) else conn['user1_discord_id']
            )
            embed.add_field(
                name='Connection', value=f'<@{other_id}> — {conn.get("connected_at", "Unknown")}', inline=False
            )
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Networking(bot))
    logging.getLogger('VEKA').info('Networking cog loaded successfully')
