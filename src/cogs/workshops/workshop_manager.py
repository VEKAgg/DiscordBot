import asyncio
import nextcord
from nextcord.ext import commands
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from src.database.database import db, get_or_create_user

logger = logging.getLogger('VEKA.workshops')


class WorkshopManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()

    def cog_unload(self):
        self.scheduler.shutdown()

    @commands.group(name='workshop', invoke_without_command=True)
    async def workshop(self, ctx):
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(title='📚 Workshop Commands',
                                   description='Manage and participate in virtual workshops!',
                                   color=nextcord.Color.orange())
            embed.add_field(name='Available Commands', inline=False, value=(
                '`!workshop create` - Create a new workshop\n'
                '`!workshop list` - List upcoming workshops\n'
                '`!workshop info <id>` - Get workshop details\n'
                '`!workshop signup <id>` - Sign up for a workshop\n'
            ))
            await ctx.send(embed=embed)

    @workshop.command(name='create')
    @commands.has_permissions(manage_events=True)
    async def workshop_create(self, ctx):
        try:
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            await ctx.send("📝 What's the title of your workshop?")
            title = (await self.bot.wait_for('message', check=check, timeout=60)).content

            await ctx.send('📋 Provide a description:')
            description = (await self.bot.wait_for('message', check=check, timeout=120)).content

            await ctx.send('🗓️ Date and time? (Format: YYYY-MM-DD HH:MM)')
            date_str = (await self.bot.wait_for('message', check=check, timeout=60)).content
            try:
                workshop_date = datetime.strptime(date_str, '%Y-%m-%d %H:%M')
            except ValueError:
                await ctx.send('❌ Invalid date format. Workshop creation cancelled.')
                return
            if workshop_date <= datetime.utcnow():
                await ctx.send('❌ Workshop date must be in the future. Cancelled.')
                return

            await ctx.send('⏱️ Duration in minutes?')
            try:
                duration = int((await self.bot.wait_for('message', check=check, timeout=60)).content)
                if duration <= 0:
                    raise ValueError
            except ValueError:
                await ctx.send('❌ Invalid duration. Workshop creation cancelled.')
                return

            await ctx.send('👥 Max participants? (0 = unlimited)')
            try:
                max_participants = int((await self.bot.wait_for('message', check=check, timeout=60)).content)
                if max_participants < 0:
                    raise ValueError
            except ValueError:
                await ctx.send('❌ Invalid number. Workshop creation cancelled.')
                return

            workshop_id = f"ws-{int(datetime.utcnow().timestamp())}"
            host = await get_or_create_user(str(ctx.author.id))

            await db.execute(
                """
                INSERT INTO workshops (id, title, description, workshop_date, duration, max_participants, created_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                workshop_id, title, description, workshop_date, duration, max_participants, host['id']
            )

            self._schedule_reminders(workshop_id, title, workshop_date)

            embed = nextcord.Embed(title='✅ Workshop Created', color=nextcord.Color.orange())
            embed.add_field(name='Title', value=title, inline=False)
            embed.add_field(name='Date & Time', value=workshop_date.strftime('%Y-%m-%d %H:%M'), inline=True)
            embed.add_field(name='Duration', value=f'{duration} minutes', inline=True)
            embed.add_field(name='Workshop ID', value=f'`{workshop_id}`', inline=False)
            embed.add_field(name='Sign Up', value=f'`!workshop signup {workshop_id}`', inline=False)
            await ctx.send(embed=embed)

        except asyncio.TimeoutError:
            await ctx.send('⏱️ Workshop creation timed out.')

    @workshop.command(name='list')
    async def workshop_list(self, ctx):
        now = datetime.utcnow()
        rows = await db.fetch_many(
            "SELECT * FROM workshops WHERE workshop_date > $1 ORDER BY workshop_date ASC", now
        )
        if not rows:
            await ctx.send('📅 No upcoming workshops scheduled.')
            return

        embed = nextcord.Embed(title='📅 Upcoming Workshops',
                               description=f'{len(rows)} upcoming workshops',
                               color=nextcord.Color.orange())
        for w in rows:
            diff = w['workshop_date'] - now
            days, rem = diff.days, diff.seconds
            h, m = rem // 3600, (rem % 3600) // 60
            time_str = f"{days}d {h}h {m}m" if days else f"{h}h {m}m"

            count_row = await db.fetch_one(
                "SELECT COUNT(*) AS n FROM workshop_participants WHERE workshop_id = $1", w['id']
            )
            count = count_row['n']
            max_str = f"/{w['max_participants']}" if w['max_participants'] > 0 else ''

            embed.add_field(
                name=f"📚 {w['title']}",
                value=(
                    f"**ID:** `{w['id']}`\n"
                    f"**When:** {w['workshop_date'].strftime('%Y-%m-%d %H:%M')} (in {time_str})\n"
                    f"**Duration:** {w['duration']} minutes\n"
                    f"**Participants:** {count}{max_str}\n"
                    f"**Sign up:** `!workshop signup {w['id']}`"
                ),
                inline=False
            )
        await ctx.send(embed=embed)

    @workshop.command(name='info')
    async def workshop_info(self, ctx, workshop_id: str):
        w = await db.fetch_one("SELECT * FROM workshops WHERE id = $1", workshop_id)
        if not w:
            await ctx.send('❌ Workshop not found.')
            return

        count_row = await db.fetch_one(
            "SELECT COUNT(*) AS n FROM workshop_participants WHERE workshop_id = $1", workshop_id
        )
        embed = nextcord.Embed(title=f"📚 {w['title']}", description=w['description'],
                               color=nextcord.Color.orange())
        embed.add_field(name='Date', value=w['workshop_date'].strftime('%Y-%m-%d %H:%M'), inline=True)
        embed.add_field(name='Duration', value=f"{w['duration']} min", inline=True)
        max_str = str(w['max_participants']) if w['max_participants'] > 0 else 'Unlimited'
        embed.add_field(name='Capacity', value=f"{count_row['n']}/{max_str}", inline=True)
        embed.add_field(name='Sign Up', value=f'`!workshop signup {workshop_id}`', inline=False)
        await ctx.send(embed=embed)

    @workshop.command(name='signup')
    async def workshop_signup(self, ctx, workshop_id: str):
        w = await db.fetch_one("SELECT * FROM workshops WHERE id = $1", workshop_id)
        if not w:
            await ctx.send('❌ Workshop not found. Use `!workshop list` to see available workshops.')
            return
        if w['workshop_date'] <= datetime.utcnow():
            await ctx.send('❌ This workshop has already started or ended.')
            return

        user = await get_or_create_user(str(ctx.author.id))
        existing = await db.fetch_one(
            "SELECT 1 FROM workshop_participants WHERE workshop_id = $1 AND user_id = $2",
            workshop_id, user['id']
        )
        if existing:
            await ctx.send("⚠️ You're already signed up for this workshop!")
            return

        if w['max_participants'] > 0:
            count = await db.fetch_one(
                "SELECT COUNT(*) AS n FROM workshop_participants WHERE workshop_id = $1", workshop_id
            )
            if count['n'] >= w['max_participants']:
                await ctx.send('❌ This workshop is already full.')
                return

        await db.execute(
            "INSERT INTO workshop_participants (workshop_id, user_id) VALUES ($1, $2)",
            workshop_id, user['id']
        )

        embed = nextcord.Embed(
            title='✅ Workshop Registration Confirmed',
            description=f"You've signed up for **{w['title']}**!",
            color=nextcord.Color.orange()
        )
        embed.add_field(
            name='📅 Details',
            value=f"**Date:** {w['workshop_date'].strftime('%Y-%m-%d %H:%M')}\n**Duration:** {w['duration']} minutes",
            inline=False
        )
        await ctx.send(embed=embed)

    def _schedule_reminders(self, workshop_id: str, title: str, workshop_date: datetime):
        now = datetime.utcnow()
        for delta, label, job_suffix in [
            (timedelta(days=1), '1 day', '1day'),
            (timedelta(hours=1), '1 hour', '1hour'),
        ]:
            fire_at = workshop_date - delta
            if now < fire_at:
                self.scheduler.add_job(
                    self._send_reminder,
                    trigger=DateTrigger(fire_at),
                    args=[workshop_id, title, label],
                    id=f"{workshop_id}_{job_suffix}",
                    replace_existing=True,
                )

    async def _send_reminder(self, workshop_id: str, title: str, time_left: str):
        w = await db.fetch_one("SELECT * FROM workshops WHERE id = $1", workshop_id)
        if not w:
            return
        participants = await db.fetch_many(
            """
            SELECT u.discord_id FROM workshop_participants wp
              JOIN users u ON u.id = wp.user_id
             WHERE wp.workshop_id = $1
            """,
            workshop_id
        )
        embed = nextcord.Embed(
            title='⏰ Workshop Reminder',
            description=f"Your workshop **{title}** starts in **{time_left}**!",
            color=nextcord.Color.orange()
        )
        embed.add_field(
            name='📅 Details',
            value=f"**Date:** {w['workshop_date'].strftime('%Y-%m-%d %H:%M')}\n**Duration:** {w['duration']} minutes",
            inline=False
        )
        for p in participants:
            try:
                user = await self.bot.fetch_user(int(p['discord_id']))
                await user.send(embed=embed)
            except Exception as e:
                logger.error(f"Failed to send reminder to {p['discord_id']}: {e}")


def setup(bot):
    bot.add_cog(WorkshopManager(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.workshops.workshop_manager')
