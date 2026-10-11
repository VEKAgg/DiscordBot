"""One guild-scoped mentorship workflow. Legacy records are participant-only read-only history."""

import logging

import nextcord
from nextcord.ext import commands, tasks

from src.config.config import MENTORSHIP_CATEGORIES, MENTORSHIP_ROLES
from src.services.mentorship_service import MentorshipService
from src.utils.embed_limits import bounded_items, clip_text
from src.utils.embeds import info_embed, success_embed
from src.utils.outbound import outbound
from src.utils.roles import punitive_role_problem
from src.utils.safety import ValidationError, safe_background_task, safe_command, safe_send, safe_slash_command

logger = logging.getLogger('VEKA.mentorship')


class Mentorship(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.mentorship_service = MentorshipService(bot)

    async def cog_ready(self):
        if not self.check_in_loop.is_running():
            self.check_in_loop.start()

    def cog_unload(self):
        self.check_in_loop.cancel()

    @staticmethod
    def _actor(target):
        return target.user if isinstance(target, nextcord.Interaction) else target.author

    @staticmethod
    def _guild(target):
        if target.guild is None:
            raise ValidationError('Use mentorship commands in a server.')
        return target.guild.id

    @staticmethod
    async def _defer(target):
        if isinstance(target, nextcord.Interaction) and not target.response.is_done():
            await target.response.defer(ephemeral=True)

    async def _reply(self, target, title, description, *, success=False, personal=False):
        builder = success_embed if success else info_embed
        embed = await builder(
            title, clip_text(description, 3000), user=self._actor(target), contributor_source=__name__
        )
        if personal and not isinstance(target, nextcord.Interaction):
            result = await outbound.dm(
                self._actor(target), kind='mentorship_private_records', embed=embed, essential=True
            )
            await self._reply(
                target,
                'Private Mentorship Records',
                'Sent in DM.' if result.ok else 'Unable to DM your records. Use the slash command for private output.',
            )
            return
        await safe_send(target, embed=embed, ephemeral=True)

    async def _assign_registration_role(self, guild, member, role_name: str) -> tuple[bool, str]:
        if guild is None:
            return False, 'Role skipped: registration roles are only available in a server.'
        role = nextcord.utils.get(guild.roles, name=role_name)
        if role is None:
            try:
                role = await guild.create_role(
                    name=role_name,
                    permissions=nextcord.Permissions.none(),
                    color=nextcord.Color.blue() if role_name == 'Mentor' else nextcord.Color.green(),
                    reason='Mentorship registration',
                )
            except Exception as exc:
                logger.warning('Unable to create enrollment role in guild %s: %s', guild.id, type(exc).__name__)
                return False, 'Role skipped: the bot could not create the decorative role.'
        problem = punitive_role_problem(role, guild)
        if problem:
            return False, f'Role skipped: {problem}. No role was assigned.'
        try:
            await member.add_roles(role, reason='Mentorship registration')
        except Exception as exc:
            logger.warning('Unable to assign enrollment role in guild %s: %s', guild.id, type(exc).__name__)
            return False, 'Role skipped: the bot could not assign the decorative role.'
        return True, f'The {role_name} role was assigned.'

    async def _register(self, target, role: str, skills=None, bio=None, categories=None):
        guild_id = self._guild(target)
        role = role.lower()
        if role not in MENTORSHIP_ROLES:
            raise ValidationError('Choose mentor or mentee.')
        await self._defer(target)
        actor = self._actor(target)
        if role == 'mentor':
            await self.mentorship_service.register_mentor(guild_id, str(actor.id), skills, bio, categories=categories)
            text = 'Your mentor availability is registered in this server. Networking profile unchanged.'
        else:
            text = 'You can request mentorship with `/mentor request`; the request records your consent.'
        _, role_message = await self._assign_registration_role(target.guild, actor, role.title())
        await self._reply(
            target,
            'Registration Complete',
            f'{text}\n{role_message}\nReminders are opt-in via `/mentor reminders`.',
            success=True,
        )

    async def _list(self, target, category=None, page=1):
        guild_id = self._guild(target)
        await self._defer(target)
        if category is not None:
            category = category.strip().lower().replace(' ', '_')
            category = None if category in {'all', ''} else category
        rows = await self.mentorship_service.find_mentors(guild_id, category, page)
        text = f'Page {page}. Available mentors in this server (including newcomers):\n'
        for row in rows[:5]:
            text += f'<@{row["discord_id"]}> · {bounded_items(row["categories"], 180)}\n'
            text += f'Skills: {bounded_items(row["skills"], 180)}\n{clip_text(row["bio"], 180)}\n'
        if not rows:
            text += 'No available mentors on this page.'
        if len(rows) > 5:
            text += f'\nMore results: page {page + 1}.' if page < 1000 else '\nPage limit reached.'
        await self._reply(target, 'Available Mentors', text)

    async def _notify(self, guild, user_id, title, description):
        member = guild.get_member(int(user_id))
        if member is None:
            return
        embed = await info_embed(title, description, user=member, contributor_source=__name__)
        try:
            await outbound.dm(member, kind='mentorship_update', embed=embed)
        except Exception as exc:
            logger.warning('Optional mentorship notification failed: %s', type(exc).__name__)

    async def _request(self, target, mentor, category, message=''):
        guild_id = self._guild(target)
        if mentor.bot or target.guild.get_member(mentor.id) is None:
            raise ValidationError('Choose a non-bot member of this server.')
        await self._defer(target)
        actor = self._actor(target)
        category = category.strip().lower().replace(' ', '_')
        row = await self.mentorship_service.create_mentorship_request(
            guild_id, str(mentor.id), str(actor.id), category, message
        )
        await self._reply(
            target,
            'Request Recorded',
            f'Mentorship `M{row["id"]}` is pending mentor acceptance. DM delivery is not guaranteed.',
            success=True,
        )
        await self._notify(
            target.guild,
            mentor.id,
            'Mentorship Request',
            f'<@{actor.id}> requested {category} mentorship (`M{row["id"]}`) in {clip_text(target.guild.name, 120)}. '
            f'\n{clip_text(row["request_message"], 1000)}\nUse `/mentor accept` for this member in that server.',
        )

    async def _accept(self, target, mentee):
        guild_id = self._guild(target)
        await self._defer(target)
        actor = self._actor(target)
        row = await self.mentorship_service.find_live_pair(guild_id, str(actor.id), str(mentee.id), 'pending')
        if row is None:
            raise ValidationError('No pending request for you as mentor in this server.')
        await self.mentorship_service.transition(guild_id, row['id'], str(actor.id), 'accept')
        await self._reply(target, 'Mentorship Accepted', f'Mentorship `M{row["id"]}` is active.', success=True)
        await self._notify(target.guild, mentee.id, 'Mentorship Accepted', f'Mentorship M{row["id"]} is now active.')

    @staticmethod
    def _id(value: str):
        if not value.startswith('M') or not value[1:].isascii() or not value[1:].isdigit() or len(value) > 11:
            raise ValidationError(
                'Use a canonical ID such as M123 from `/mentor engagements`. Old match IDs are unsupported.'
            )
        result = int(value[1:])
        if not 0 < result < 2**31:
            raise ValidationError('Invalid canonical mentorship ID.')
        return result

    async def _end(self, target, mentorship_id: int, outcome='successful'):
        guild_id = self._guild(target)
        await self._defer(target)
        row = await self.mentorship_service.transition(
            guild_id, mentorship_id, str(self._actor(target).id), 'end', outcome
        )
        credit = (
            ', '.join(f'<@{award["discord_id"]}>: {award["points"]} XP' for award in row['awards'])
            or 'No XP awards for this action.'
        )
        await self._reply(
            target, 'Mentorship Closed', f'M{row["id"]}: {row["status"]} / {row["outcome"]}.\n{credit}', success=True
        )
        other = (
            row['mentee_discord_id']
            if row['mentor_discord_id'] == str(self._actor(target).id)
            else row['mentor_discord_id']
        )
        await self._notify(
            target.guild, other, 'Mentorship Closed', f'M{row["id"]}: {row["status"]} / {row["outcome"]}.\n{credit}'
        )

    async def _complete(self, target, mentee):
        guild_id = self._guild(target)
        await self._defer(target)
        row = await self.mentorship_service.find_live_pair(
            guild_id, str(self._actor(target).id), str(mentee.id), 'active'
        )
        if row is None:
            raise ValidationError('No active mentorship for you as mentor in this server.')
        await self._end(target, row['id'])

    async def _engagements(self, target, page=1, *, legacy=False):
        guild_id = None if legacy else self._guild(target)
        await self._defer(target)
        rows = await self.mentorship_service.get_user_mentorships(str(self._actor(target).id), guild_id, page)
        text = (
            'Unbound legacy history is read-only; no inferred guild or historical rewards.\n'
            if legacy
            else 'Current-server engagements. Use M-prefixed IDs with `/mentor end`.\n'
        )
        for row in rows[:5]:
            label = f'Legacy #{row["id"]}' if legacy else f'M{row["id"]}'
            text += f'**{label}** · {clip_text(row["category"], 100)} · {clip_text(row["status"], 40)}\n'
            other = (
                row['mentee_discord_id']
                if row['mentor_discord_id'] == str(self._actor(target).id)
                else row['mentor_discord_id']
            )
            text += f'Partner: <@{other}>\n' if other else 'Partner unavailable in legacy record.\n'
            if not legacy and row['status'] == 'pending':
                text += f'Request: {clip_text(row["request_message"], 180)}\n'
        if not rows:
            text += 'No records on this page.'
        if len(rows) > 5 and page < 1000:
            text += f'\nMore results: page {page + 1}.'
        await self._reply(target, 'Mentorship History' if legacy else 'Your Mentorships', text, personal=True)

    async def _stats(self, target):
        guild_id = self._guild(target)
        await self._defer(target)
        row = await self.mentorship_service.get_mentorship_stats(guild_id)
        await self._reply(
            target,
            'Server Mentorship Stats',
            f'Total: {row["total"]}\nActive: {row["active"]}\nCompleted: {row["completed"]}\nUnbound history is excluded.',
        )

    async def _availability(self, target, available):
        guild_id = self._guild(target)
        await self._defer(target)
        await self.mentorship_service.set_availability(guild_id, str(self._actor(target).id), available)
        await self._reply(
            target,
            'Availability Updated',
            'Available for new requests.'
            if available
            else 'Paused; no new requests. Existing engagements are unchanged.',
            success=True,
        )

    async def _reminders(self, target, enabled):
        guild_id = self._guild(target)
        await self._defer(target)
        await self.mentorship_service.set_reminders(guild_id, str(self._actor(target).id), enabled)
        await self._reply(
            target,
            'Reminder Preference Saved',
            'Opted in; first check-in is no sooner than seven days from now.'
            if enabled
            else 'Check-in reminders disabled.',
            success=True,
        )

    async def _help(self, target):
        await self._reply(
            target,
            'Mentorship Commands',
            'Guild-scoped, opt-in mentorship. `/mentor` and `!mentor`: register, apply, list, request, accept, complete, end, cancel, engagements, history, stats, availability, reminders.\n'
            'Mentor certifies successful completion (50/25 XP once); either participant may cancel. Roles are optional decoration.\n'
            'Use M-prefixed canonical IDs; old match IDs are read-only archive. Reminders default off.',
        )

    @nextcord.slash_command(name='mentor', description='Guild-scoped opt-in mentorship')
    async def mentor(self, interaction: nextcord.Interaction):
        await self._help(interaction)

    @mentor.subcommand(
        name='register', description='Opt in as mentor or prepare as mentee; role assignment is optional'
    )
    @safe_slash_command(requires_db=True)
    async def mentor_register_slash(self, interaction: nextcord.Interaction, role: str):
        await self._register(interaction, role)

    @mentor.subcommand(
        name='apply', description='Publish your mentor availability without changing your networking profile'
    )
    @safe_slash_command(requires_db=True)
    async def mentor_apply(self, interaction: nextcord.Interaction, skills: str, bio: str, categories: str = ''):
        chosen = (
            [c.strip().lower().replace(' ', '_') for c in categories.split(',') if c.strip()] if categories else None
        )
        await self._register(interaction, 'mentor', skills, bio, chosen)

    @mentor.subcommand(name='list', description='List available mentors, five per page')
    @safe_slash_command(requires_db=True)
    async def mentor_list_slash(
        self,
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(
            required=False, choices={c.replace('_', ' ').title(): c for c in MENTORSHIP_CATEGORIES}
        ),
        page: int = 1,
    ):
        await self._list(interaction, category, page)

    @mentor.subcommand(name='request', description='Request an available mentor in this server')
    @safe_slash_command(requires_db=True)
    async def mentor_request_slash(
        self,
        interaction: nextcord.Interaction,
        mentor: nextcord.Member,
        category: str = nextcord.SlashOption(choices={c.replace('_', ' ').title(): c for c in MENTORSHIP_CATEGORIES}),
        message: str = '',
    ):
        await self._request(interaction, mentor, category, message)

    @mentor.subcommand(name='accept', description='Mentor accepts a pending request')
    @safe_slash_command(requires_db=True)
    async def mentor_accept_slash(self, interaction: nextcord.Interaction, mentee: nextcord.Member):
        await self._accept(interaction, mentee)

    @mentor.subcommand(name='complete', description='Mentor certifies successful completion')
    @safe_slash_command(requires_db=True)
    async def mentor_complete_slash(self, interaction: nextcord.Interaction, mentee: nextcord.Member):
        await self._complete(interaction, mentee)

    @mentor.subcommand(name='end', description='Close a canonical engagement (use M-prefixed ID, not old match ID)')
    @safe_slash_command(requires_db=True)
    async def mentor_end(self, interaction: nextcord.Interaction, mentorship_id: str, outcome: str = 'successful'):
        await self._end(interaction, self._id(mentorship_id), outcome)

    @mentor.subcommand(name='cancel', description='Either participant cancels a pending/active engagement without XP')
    @safe_slash_command(requires_db=True)
    async def mentor_cancel(self, interaction: nextcord.Interaction, mentorship_id: str):
        await self._end(interaction, self._id(mentorship_id), 'cancelled')

    @mentor.subcommand(name='engagements', description='View your current-server canonical engagements')
    @safe_slash_command(requires_db=True)
    async def mentor_engagements(self, interaction: nextcord.Interaction, page: int = 1):
        await self._engagements(interaction, page)

    @mentor.subcommand(name='history', description='View your unbound legacy history, read-only')
    @safe_slash_command(requires_db=True)
    async def mentor_history(self, interaction: nextcord.Interaction, page: int = 1):
        await self._engagements(interaction, page, legacy=True)

    @mentor.subcommand(name='stats', description='Current-server mentorship statistics')
    @safe_slash_command(requires_db=True)
    async def mentor_stats_slash(self, interaction: nextcord.Interaction):
        await self._stats(interaction)

    @mentor.subcommand(name='availability', description='Pause/resume mentor availability')
    @safe_slash_command(requires_db=True)
    async def mentor_availability(self, interaction: nextcord.Interaction, available: bool):
        await self._availability(interaction, available)

    @mentor.subcommand(name='reminders', description='Opt in/out of weekly check-in DMs (default off)')
    @safe_slash_command(requires_db=True)
    async def mentor_reminders(self, interaction: nextcord.Interaction, enabled: bool):
        await self._reminders(interaction, enabled)

    @commands.group(name='mentor', invoke_without_command=True)
    async def mentor_prefix(self, ctx):
        await self._help(ctx)

    @mentor_prefix.command(name='register')
    @safe_command(requires_db=True)
    async def mentor_register_prefix(self, ctx, role: str):
        await self._register(ctx, role)

    @mentor_prefix.command(name='apply')
    @safe_command(requires_db=True)
    async def mentor_apply_prefix(self, ctx, skills: str, *, bio: str):
        categories = None
        if bio.startswith('--categories '):
            pieces = bio.removeprefix('--categories ').split('|', 1)
            if len(pieces) != 2:
                raise ValidationError('Use `!mentor apply "skills" --categories programming,career | bio`.')
            categories = [c.strip().lower().replace(' ', '_') for c in pieces[0].split(',') if c.strip()]
            bio = pieces[1].strip()
        await self._register(ctx, 'mentor', skills, bio, categories)

    @mentor_prefix.command(name='list')
    @safe_command(requires_db=True)
    async def mentor_list_prefix(self, ctx, category: str = None, page: int = 1):
        await self._list(ctx, category, page)

    @mentor_prefix.command(name='request')
    @safe_command(requires_db=True)
    async def mentor_request_prefix(self, ctx, mentor: nextcord.Member, category: str, *, message: str = ''):
        await self._request(ctx, mentor, category, message)

    @mentor_prefix.command(name='accept')
    @safe_command(requires_db=True)
    async def mentor_accept_prefix(self, ctx, mentee: nextcord.Member):
        await self._accept(ctx, mentee)

    @mentor_prefix.command(name='complete')
    @safe_command(requires_db=True)
    async def mentor_complete_prefix(self, ctx, mentee: nextcord.Member):
        await self._complete(ctx, mentee)

    @mentor_prefix.command(name='end')
    @safe_command(requires_db=True)
    async def mentor_end_prefix(self, ctx, mentorship_id: str, outcome: str = 'successful'):
        await self._end(ctx, self._id(mentorship_id), outcome)

    @mentor_prefix.command(name='cancel')
    @safe_command(requires_db=True)
    async def mentor_cancel_prefix(self, ctx, mentorship_id: str):
        await self._end(ctx, self._id(mentorship_id), 'cancelled')

    @mentor_prefix.command(name='engagements')
    @safe_command(requires_db=True)
    async def mentor_engagements_prefix(self, ctx, page: int = 1):
        await self._engagements(ctx, page)

    @mentor_prefix.command(name='history')
    @safe_command(requires_db=True)
    async def mentor_history_prefix(self, ctx, page: int = 1):
        await self._engagements(ctx, page, legacy=True)

    @mentor_prefix.command(name='stats')
    @safe_command(requires_db=True)
    async def mentor_stats_prefix(self, ctx):
        await self._stats(ctx)

    @mentor_prefix.command(name='availability')
    @safe_command(requires_db=True)
    async def mentor_availability_prefix(self, ctx, available: bool):
        await self._availability(ctx, available)

    @mentor_prefix.command(name='reminders')
    @safe_command(requires_db=True)
    async def mentor_reminders_prefix(self, ctx, enabled: bool):
        await self._reminders(ctx, enabled)

    @tasks.loop(hours=24)
    @safe_background_task(name='mentorship_checkins')
    async def check_in_loop(self):
        service = self.mentorship_service
        rows = await service.due_reminders()
        groups: dict[tuple[int, int, int, str], list] = {}
        for row in rows:
            groups.setdefault((row['guild_id'], row['user_id'], row['revision'], row['discord_id']), []).append(row)
        failures = 0
        for guild_id, user_id, revision, discord_id in groups:
            if not await service.claim_reminder(guild_id, user_id, revision):
                continue
            guild = self.bot.get_guild(guild_id)
            member = guild.get_member(int(discord_id)) if guild else None
            if member is None:
                continue
            embed = await info_embed(
                'Mentorship Check-in',
                'You opted in to check-ins for this server. Use `/mentor engagements` to view current status; `/mentor reminders false` to opt out.',
                user=member,
                contributor_source=__name__,
            )
            matches = await service.current_reminder_matches(guild_id, user_id, revision)
            if not matches:
                continue
            for match in matches[:10]:
                embed.add_field(name=f'M{match["id"]}', value=clip_text(match['category'], 100), inline=False)
            result = await outbound.dm(
                member,
                kind='mentorship_checkin',
                embed=embed,
                dedupe_key=f'mentorship-reminder:{guild_id}:{user_id}:{revision}:{matches[0]["id"]}',
            )
            await service.finish_reminder(guild_id, user_id, revision, result.ok)
            failures = 0 if result.ok else failures + 1
            if failures >= 3:
                break

    @check_in_loop.before_loop
    async def before_check_in(self):
        await self.bot.wait_until_ready()


def setup(bot):
    bot.add_cog(Mentorship(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.mentorship')
