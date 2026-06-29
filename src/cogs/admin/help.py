import logging
from types import SimpleNamespace

import nextcord
from nextcord.ext import commands

from src.config.config import MAIN_GUILD_ID, MAIN_SERVER_INVITE_URL
from src.utils.embeds import info_embed
from src.utils.safety import safe_send, safe_slash_command
from src.utils.security.rbac import Role, rbac

logger = logging.getLogger('VEKA.admin.help')


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _get_user_role(self, interaction: nextcord.Interaction) -> Role:
        return rbac.get_user_role(interaction)

    def _is_main_guild(self, interaction: nextcord.Interaction | None) -> bool:
        if interaction is None:
            return True
        guild = getattr(interaction, 'guild', None)
        return guild is not None and guild.id == MAIN_GUILD_ID

    async def _build_help_embed(
        self, interaction: nextcord.Interaction | None = None, command: str | None = None
    ) -> nextcord.Embed:
        user_role = Role.USER
        user = None
        if interaction:
            user = getattr(interaction, 'author', None) or getattr(interaction, 'user', None)
            user_role = self._get_user_role(interaction)

        is_staff = ROLE_HIERARCHY.index(user_role) >= ROLE_HIERARCHY.index(Role.STAFF)
        is_founder = user_role == Role.FOUNDER
        is_main = self._is_main_guild(interaction)

        if command is None:
            if is_main:
                embed = await self._build_main_help(interaction, user, user_role, is_staff, is_founder)
            else:
                embed = await self._build_external_help(interaction, user, user_role)
        else:
            embed = await self._build_command_help(interaction, user, command)

        return embed

    async def _build_main_help(
        self,
        interaction: nextcord.Interaction | None,
        user,
        user_role: Role,
        is_staff: bool,
        is_founder: bool,
    ) -> nextcord.Embed:
        embed = await info_embed(
            title='VEKA Bot Help',
            description='Here are all available commands. Use `/help command:<name>` for details on a specific command.',
            contributor_source=__name__,
            user=user,
            guild=getattr(interaction, 'guild', None),
        )

        # === UTILITY ===
        utility = '`/help` - Show this help\n`/commands` - List all commands\n`/ping` - Check bot latency\n`/hello` - Greet the bot\n`/health` - Bot health status\n`/botinfo` - Bot info'
        embed.add_field(name='Utility', value=utility, inline=False)

        # === PROFESSIONAL NETWORKING ===
        networking = (
            '`/profile setup` - Create your profile\n'
            '`/profile edit` - Edit your profile\n'
            '`/profile view [member]` - View a profile\n'
            '`/connect request @member [msg]` - Send connection request\n'
            '`/connect accept @member` - Accept connection\n'
            '`/connect decline @member` - Decline connection\n'
            '`/connect list` - View your connections'
        )
        embed.add_field(name='Professional Networking', value=networking, inline=False)

        # === MARKETPLACE ===
        marketplace = (
            '`/marketplace post` - Create a listing\n'
            '`/marketplace browse [category]` - Browse listings\n'
            '`/marketplace view <id>` - View listing\n'
            '`/marketplace mylistings` - Your listings\n'
            '`/marketplace withdraw <id>` - Withdraw listing\n'
            '`/search <query>` - Advanced search\n'
            '`/watch <id>` - Add to watchlist\n'
            '`/unwatch <id>` - Remove from watchlist\n'
            '`/watchlist` - Your watchlist\n'
            '`/offer <id> <price> [msg]` - Make an offer\n'
            '`/myoffers` - Your offers\n'
            '`/featured` - Featured listings\n'
            '`/marketstats` - Marketplace stats'
        )
        embed.add_field(name='Marketplace', value=marketplace, inline=False)

        # === REVIEWS ===
        reviews = (
            '`/review <id> <1-5> [comment]` - Leave review\n'
            '`/seller [member]` - View seller profile\n'
            '`/reviews` - Your reviews\n'
            '`/helpful <review_id>` - Mark review helpful\n'
            '`/bump <listing_id>` - Bump listing'
        )
        embed.add_field(name='Reviews & Reputation', value=reviews, inline=False)

        # === RESOURCES ===
        resources = '`/resource sources` - List feed categories\n`/resource latest <category>` - Latest entries'
        embed.add_field(name='RSS / Resources', value=resources, inline=False)

        # === MENTORSHIP ===
        mentorship = (
            '`/mentor register <role>` - Register as mentor/mentee\n'
            '`/mentor list [category]` - List mentors\n'
            '`/mentor request @mentor <category>` - Request mentorship\n'
            '`/mentor accept @mentee` - Accept request\n'
            '`/mentor complete @mentee` - Complete mentorship\n'
            '`/mentor stats` - View stats'
        )
        embed.add_field(name='Mentorship', value=mentorship, inline=False)

        # === PORTFOLIO ===
        portfolio = (
            '`/portfolio add` - Add project\n'
            '`/portfolio list [@user]` - List projects\n'
            '`/portfolio view <id>` - View project\n'
            '`/portfolio delete <id>` - Delete project\n'
            '`/portfolio search <query>` - Search projects'
        )
        embed.add_field(name='Portfolio', value=portfolio, inline=False)

        # === RADIO ===
        radio = '`/radio status` - Check radio stream\n`/radio start` - Start radio (Admin)\n`/radio stop` - Stop radio (Admin)\n`/radio move <channel>` - Move radio (Admin)'
        embed.add_field(name='Radio', value=radio, inline=False)

        # === RPG ===
        rpg = '`/level [user]` - Check level & XP\n`/leaderboard` - View leaderboard\n`/activity [user]` - View activity stats'
        embed.add_field(name='Community', value=rpg, inline=False)

        # === STAFF ONLY ===
        if is_staff:
            staff_cmds = (
                '`/featurestatus` - Feature status\n'
                '`/startupchecks` - Boot checks\n'
                '`/reloadcog <name>` - Reload a cog\n'
                '`/panic` / `/lockdown` - Server lockdown'
            )
            embed.add_field(name='Staff Commands', value=staff_cmds, inline=False)

        # === FOUNDER ONLY ===
        if is_founder:
            founder_cmds = (
                '`/panic` / `/lockdown` - Toggle server lockdown\n'
                '`/broadcast <channel> <message>` - Send announcement\n'
                '`/ping_squad <message>` - Ping notification squad\n'
                '`/exportchat [channel]` - Export chat history\n'
                '`/memberinfo @user` - Member info\n'
                '`/serverinfo` - Server info'
            )
            embed.add_field(name='Founder Commands', value=founder_cmds, inline=False)

        embed.set_footer(
            text=f'Your role: {user_role.value.title()} | Roles with cooldown bypass: Intern, Donator, Active Pro, Staff, Founder'
        )
        return embed

    async def _build_external_help(
        self,
        interaction: nextcord.Interaction | None,
        user,
        _user_role: Role,
    ) -> nextcord.Embed:
        embed = await info_embed(
            title='VEKA Bot Help',
            description='Commands available in this server.',
            contributor_source=__name__,
            user=user,
            guild=getattr(interaction, 'guild', None),
        )

        # === UTILITY ===
        utility = '`/help` - Show this help\n`/commands` - List all commands\n`/ping` - Check bot latency\n`/hello` - Greet the bot\n`/health` - Bot health status\n`/botinfo` - Bot info'
        embed.add_field(name='Utility', value=utility, inline=False)

        # === COMMUNITY ===
        community = (
            '`/level [user]` - Check level & XP\n'
            '`/leaderboard` - View leaderboard\n'
            '`/activity [user]` - View activity stats\n'
            '`/radio status` - Check radio stream'
        )
        embed.add_field(name='Community', value=community, inline=False)

        # === PROFILES ===
        profiles = '`/profile view [member]` - View a profile'
        embed.add_field(name='Profiles', value=profiles, inline=False)

        # === RESOURCES ===
        resources = '`/resource sources` - List feed categories\n`/resource latest <category>` - Latest entries'
        embed.add_field(name='RSS / Resources', value=resources, inline=False)

        # === OWNER ONLY ===
        from src.config.config import OWNER_DISCORD_ID

        is_owner = user and user.id == OWNER_DISCORD_ID
        if is_owner:
            owner_cmds = (
                '`/exportchat [channel]` - Export chat history\n'
                '`/exportstop` - Stop export\n'
                '`/memberinfo @user` - Member info\n'
                '`/serverinfo` - Server info\n'
                '`/radio start` - Start radio\n'
                '`/radio stop` - Stop radio\n'
                '`/radio move <channel>` - Move radio'
            )
            embed.add_field(name='Owner Only', value=owner_cmds, inline=False)

        embed.set_footer(text=f'Want more? Join the main VEKA community: {MAIN_SERVER_INVITE_URL}')
        return embed

    async def _build_command_help(
        self,
        interaction: nextcord.Interaction | None,
        user,
        command: str,
    ) -> nextcord.Embed:
        command = command.lower().strip('!')
        cmd = self.bot.get_command(command)

        if cmd is None:
            embed = await info_embed(
                title='Help: Command Not Found',
                description=f'Command `{command}` not found. Use `/help` to see all available commands.',
                contributor_source=__name__,
                user=user,
                guild=getattr(interaction, 'guild', None),
            )
            return embed

        embed = await info_embed(
            title=f'Help: {cmd.name}',
            description=cmd.help or 'No description available.',
            contributor_source=__name__,
            user=user,
            guild=getattr(interaction, 'guild', None),
        )

        if cmd.aliases:
            embed.add_field(name='Aliases', value=', '.join(cmd.aliases), inline=False)

        usage = f'!{cmd.name}'
        if cmd.signature:
            usage += f' {cmd.signature}'
        embed.add_field(name='Usage', value=f'`{usage}`', inline=False)

        examples = {
            'ping': '`/ping` - Check bot latency',
            'help': '`/help` - Show overview\n`/help ping` - Show ping usage',
            'profile': '`/profile setup` - Create profile\n`/profile view` - View profile',
            'connect': '`/connect request @user` - Send request',
            'marketplace': '`/marketplace post` - Create listing\n`/marketplace browse` - Browse',
            'review': '`/review 123 5 Great seller` - Leave review',
        }

        if cmd.name in examples:
            embed.add_field(name='Examples', value=examples[cmd.name], inline=False)

        return embed

    @commands.command(name='help')
    async def help_prefix(self, ctx, command: str = None):
        """Shows help about commands and categories"""

        # Build a minimal interaction-like object for role detection
        mini = SimpleNamespace(user=ctx.author, guild=ctx.guild)
        embed = await self._build_help_embed(interaction=mini, command=command)
        try:
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f'Error in help command: {str(e)}')
            await ctx.send('An error occurred while showing the help message.')

    @nextcord.slash_command(name='help', description='Shows help about commands and categories')
    @safe_slash_command()
    async def help_slash(self, interaction: nextcord.Interaction, command: str = None):
        """Shows help about commands and categories"""
        embed = await self._build_help_embed(interaction=interaction, command=command)
        await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='commands', description='List all available commands')
    @safe_slash_command()
    async def commands_slash(self, interaction: nextcord.Interaction):
        """List all available commands with role-based visibility"""
        embed = await self._build_help_embed(interaction=interaction, command=None)
        await safe_send(interaction, embed=embed, ephemeral=True)


# Import at module level for use in _build_help_embed
from src.utils.security.rbac import ROLE_HIERARCHY  # noqa: E402


def setup(bot):
    """Setup the Help cog"""
    if bot is not None:
        bot.add_cog(Help(bot))
        logging.getLogger('VEKA').info('Help cog loaded successfully')
    else:
        logging.getLogger('VEKA').error('Bot is None in Help cog setup')
