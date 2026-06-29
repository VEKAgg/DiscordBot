import logging
import re
from urllib.parse import urlparse

import nextcord
from nextcord.ext import commands

from src.services.networking_service import NetworkingService
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import safe_command, safe_send, safe_slash_command

logger = logging.getLogger('VEKA.networking')


class Networking(commands.Cog):
    @nextcord.slash_command(name='profile', description='Professional profile commands')
    async def profile(self, interaction: nextcord.Interaction):
        pass

    @nextcord.slash_command(name='connect', description='Connection request commands')
    async def connect(self, interaction: nextcord.Interaction):
        pass

    def __init__(self, bot):
        self.bot = bot
        self.svc = NetworkingService()

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

    async def _format_profile(self, target: nextcord.Member, profile: dict, user: nextcord.Member) -> nextcord.Embed:
        embed = await info_embed(
            title=f"{target.display_name}'s Professional Profile",
            description='A concise overview of community networking details.',
            contributor_source=__name__,
            user=user,
        )
        embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
        embed.add_field(name='Title', value=profile.get('title') or 'Not set', inline=False)
        embed.add_field(name='Skills', value=profile.get('skills') or 'Not set', inline=False)
        embed.add_field(name='About', value=profile.get('bio') or profile.get('experience') or 'Not set', inline=False)
        embed.add_field(name='Looking For', value=profile.get('looking_for') or 'Not set', inline=False)
        embed.add_field(name='Links', value=self._links_display(profile.get('links')), inline=False)
        embed.set_footer(text=f'Last updated: {profile.get("last_updated", "Never")}')
        return embed

    async def _build_profile_data(self, existing: dict | None, values: dict) -> dict:
        profile_data = {}
        for field in ['title', 'skills', 'bio', 'links', 'looking_for']:
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

        embed = await self._format_profile(target, profile, user=interaction.user)  # type: ignore[arg-type]
        await safe_send(interaction, embed=embed, ephemeral=True)

    @connect.subcommand(name='request', description='Send a connection request')
    @safe_slash_command(requires_db=True)
    async def connect_request(
        self,
        interaction: nextcord.Interaction,
        member: nextcord.Member,
        message: str | None = None,
    ):
        """Send a connection request to another member."""
        try:
            await self.svc.create_request(str(interaction.user.id), str(member.id), message or '')
            embed = await success_embed(
                title='Connection Request Sent',
                description=f'Your request has been sent to {member.display_name}.',
                contributor_source=__name__,
                user=interaction.user,
            )
            if message:
                embed.add_field(name='Message', value=message, inline=False)
            await safe_send(interaction, embed=embed, ephemeral=True)

            notify = await info_embed(
                title='New Connection Request',
                description=f'{interaction.user.mention} would like to connect with you.',
                contributor_source=__name__,
                user=member,
            )
            if message:
                notify.add_field(name='Message', value=message, inline=False)
            notify.add_field(
                name='Respond',
                value='Use `/connect accept` or `/connect decline` to respond.',
                inline=False,
            )
            try:
                await member.send(embed=notify)
            except nextcord.Forbidden:
                logger.info('Unable to DM %s for connection request', member.id)
        except ValueError as exc:
            embed = await error_embed(
                title='Unable to Send Request',
                description=str(exc),
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    @connect.subcommand(name='accept', description='Accept a connection request')
    @safe_slash_command(requires_db=True)
    async def connect_accept(self, interaction: nextcord.Interaction, member: nextcord.Member):
        """Accept a pending connection request from another member."""
        request = await self.svc.get_pending_request(str(member.id), str(interaction.user.id))
        if not request:
            embed = await error_embed(
                title='No Pending Request',
                description=f'No pending request found from {member.display_name}.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        await self.svc.update_request_status(request['id'], 'accepted')
        await self.svc.create_connection(str(interaction.user.id), str(member.id))

        embed = await success_embed(
            title='Connection Accepted',
            description=f'You are now connected with {member.display_name}.',
            contributor_source=__name__,
            user=interaction.user,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

        notify = await success_embed(
            title='Connection Accepted',
            description=f'{interaction.user.mention} accepted your connection request.',
            contributor_source=__name__,
            user=member,
        )
        try:
            await member.send(embed=notify)
        except nextcord.Forbidden:
            logger.info('Unable to DM %s for accepted request', member.id)

    @connect.subcommand(name='decline', description='Decline a connection request')
    @safe_slash_command(requires_db=True)
    async def connect_decline(self, interaction: nextcord.Interaction, member: nextcord.Member):
        """Decline a pending connection request from another member."""
        request = await self.svc.get_pending_request(str(member.id), str(interaction.user.id))
        if not request:
            embed = await error_embed(
                title='No Pending Request',
                description=f'No pending request found from {member.display_name}.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        await self.svc.update_request_status(request['id'], 'declined')
        embed = await success_embed(
            title='Connection Declined',
            description=f'You declined the request from {member.display_name}.',
            contributor_source=__name__,
            user=interaction.user,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)

        notify = await error_embed(
            title='Connection Declined',
            description=f'{interaction.user.mention} declined your connection request.',
            contributor_source=__name__,
            user=member,
        )
        try:
            await member.send(embed=notify)
        except nextcord.Forbidden:
            logger.info('Unable to DM %s for declined request', member.id)

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
            embed = await self._format_profile(target, profile, user=ctx.author)
        await ctx.send(embed=embed)

    @commands.command(name='setupprofile', description='Set up your professional profile')
    @safe_command(requires_db=True)
    async def setupprofile_fallback(self, ctx):
        await ctx.send('Use `/profile setup` to create your profile. Slash commands provide the best experience.')

    @commands.command(name='connect', description='Send a connection request')
    @safe_command(requires_db=True)
    async def connect_fallback(self, ctx, member: nextcord.Member, *, message: str = None):
        try:
            await self.svc.create_request(str(ctx.author.id), str(member.id), message or '')
            embed = await success_embed(
                title='Connection Request Sent',
                description=f'Your request has been sent to {member.display_name}.',
                contributor_source=__name__,
                user=ctx.author,
            )
            if message:
                embed.add_field(name='Message', value=message, inline=False)
            await ctx.send(embed=embed)
        except ValueError as exc:
            embed = await error_embed(
                title='Unable to Send Request',
                description=str(exc),
                contributor_source=__name__,
                user=ctx.author,
            )
            await ctx.send(embed=embed)

    @commands.command(name='accept', description='Accept a connection request')
    @safe_command(requires_db=True)
    async def accept_fallback(self, ctx, member: nextcord.Member):
        request = await self.svc.get_pending_request(str(member.id), str(ctx.author.id))
        if not request:
            embed = await error_embed(
                title='No Pending Request',
                description=f'No pending request found from {member.display_name}.',
                contributor_source=__name__,
                user=ctx.author,
            )
            await ctx.send(embed=embed)
            return
        await self.svc.update_request_status(request['id'], 'accepted')
        await self.svc.create_connection(str(ctx.author.id), str(member.id))
        embed = await success_embed(
            title='Connection Accepted',
            description=f'You are now connected with {member.display_name}.',
            contributor_source=__name__,
            user=ctx.author,
        )
        await ctx.send(embed=embed)

    @commands.command(name='decline', description='Decline a connection request')
    @safe_command(requires_db=True)
    async def decline_fallback(self, ctx, member: nextcord.Member):
        request = await self.svc.get_pending_request(str(member.id), str(ctx.author.id))
        if not request:
            embed = await error_embed(
                title='No Pending Request',
                description=f'No pending request found from {member.display_name}.',
                contributor_source=__name__,
                user=ctx.author,
            )
            await ctx.send(embed=embed)
            return
        await self.svc.update_request_status(request['id'], 'declined')
        embed = await success_embed(
            title='Connection Declined',
            description=f'You declined the request from {member.display_name}.',
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
