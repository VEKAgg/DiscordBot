import nextcord
from nextcord.ext import commands, tasks
import logging
from datetime import datetime, timedelta
import asyncio
from typing import List, Dict, Optional
import matplotlib.pyplot as plt
import io
import pandas as pd
import seaborn as sns
from collections import Counter, defaultdict

logger = logging.getLogger('VEKA.analytics')

class Analytics(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.mongo
        self.metrics = self.db.analytics_metrics
        self.reports = self.db.analytics_reports
        self.update_metrics.start()
        self.generate_reports.start()

    def cog_unload(self):
        self.update_metrics.cancel()
        self.generate_reports.cancel()

    @tasks.loop(minutes=15)
    async def update_metrics(self):
        """Update analytics metrics"""
        try:
            now = datetime.utcnow()
            for guild in self.bot.guilds:
                metrics = {
                    "guild_id": str(guild.id),
                    "timestamp": now,
                    "member_count": guild.member_count,
                    "online_count": len([m for m in guild.members if m.status != nextcord.Status.offline]),
                    "channel_counts": {
                        "text": len([c for c in guild.channels if isinstance(c, nextcord.TextChannel)]),
                        "voice": len([c for c in guild.channels if isinstance(c, nextcord.VoiceChannel)]),
                    }
                }

                # Add role distribution
                role_counts = Counter(role.name for member in guild.members for role in member.roles)
                metrics["role_distribution"] = dict(role_counts)

                await self.metrics.insert_one(metrics)

        except Exception as e:
            logger.error(f"Error updating metrics: {str(e)}")

    @tasks.loop(hours=24)
    async def generate_reports(self):
        """Generate daily analytics reports"""
        try:
            now = datetime.utcnow()
            day_ago = now - timedelta(days=1)

            for guild in self.bot.guilds:
                # Get metrics for the past day
                daily_metrics = await self.metrics.find({
                    "guild_id": str(guild.id),
                    "timestamp": {"$gte": day_ago}
                }).to_list(length=None)

                if not daily_metrics:
                    continue

                report = await self.analyze_metrics(guild, daily_metrics)
                await self.reports.insert_one(report)

                # Notify admins if configured
                if admin_channel := await self.get_admin_channel(guild):
                    await self.send_daily_report(admin_channel, report)

        except Exception as e:
            logger.error(f"Error generating reports: {str(e)}")

    async def analyze_metrics(self, guild: nextcord.Guild, metrics: List[Dict]) -> Dict:
        """Analyze metrics and generate insights"""
        try:
            # Convert to pandas DataFrame for analysis
            df = pd.DataFrame(metrics)
            
            # Basic statistics
            stats = {
                "avg_member_count": df["member_count"].mean(),
                "peak_member_count": df["member_count"].max(),
                "avg_online_ratio": (df["online_count"] / df["member_count"]).mean(),
                "timestamp": datetime.utcnow()
            }

            # Member growth
            first = df.iloc[0]["member_count"]
            last = df.iloc[-1]["member_count"]
            stats["member_growth"] = last - first

            # Peak activity hours
            df["hour"] = df["timestamp"].dt.hour
            peak_hours = df.groupby("hour")["online_count"].mean().nlargest(3)
            stats["peak_hours"] = peak_hours.index.tolist()

            # Role analysis
            role_data = defaultdict(list)
            for metric in metrics:
                for role, count in metric["role_distribution"].items():
                    role_data[role].append(count)

            role_stats = {}
            for role, counts in role_data.items():
                role_stats[role] = {
                    "avg": sum(counts) / len(counts),
                    "max": max(counts),
                    "growth": counts[-1] - counts[0]
                }

            stats["role_analytics"] = role_stats

            return {
                "guild_id": str(guild.id),
                "guild_name": guild.name,
                "date": datetime.utcnow().date(),
                "stats": stats
            }

        except Exception as e:
            logger.error(f"Error analyzing metrics: {str(e)}")
            return {}

    async def get_admin_channel(self, guild: nextcord.Guild) -> Optional[nextcord.TextChannel]:
        """Get the admin channel for a guild"""
        settings = await self.db.server_settings.find_one({"guild_id": str(guild.id)})
        if settings and (channel_id := settings.get("admin_channel_id")):
            return guild.get_channel(int(channel_id))
        return None

    async def send_daily_report(self, channel: nextcord.TextChannel, report: Dict):
        """Send daily analytics report to admin channel"""
        stats = report["stats"]
        
        embed = nextcord.Embed(
            title="📊 Daily Analytics Report",
            description=f"Analytics for {report['guild_name']}",
            color=nextcord.Color.blue(),
            timestamp=stats["timestamp"]
        )

        # Member statistics
        embed.add_field(
            name="👥 Member Activity",
            value=f"""
            Average Members: {stats['avg_member_count']:.0f}
            Peak Members: {stats['peak_member_count']}
            Member Growth: {stats['member_growth']:+d}
            Average Online: {stats['avg_online_ratio']:.1%}
            """,
            inline=False
        )

        # Peak hours
        embed.add_field(
            name="⏰ Peak Activity Hours",
            value=", ".join(f"{hour}:00" for hour in stats["peak_hours"]),
            inline=False
        )

        # Top growing roles
        role_growth = sorted(
            stats["role_analytics"].items(),
            key=lambda x: x[1]["growth"],
            reverse=True
        )[:3]

        if role_growth:
            embed.add_field(
                name="📈 Top Growing Roles",
                value="\n".join(
                    f"{role}: {data['growth']:+d} members"
                    for role, data in role_growth
                ),
                inline=False
            )

        # Generate and attach activity graph
        fig = await self.generate_activity_graph(report)
        if fig:
            buf = io.BytesIO()
            fig.savefig(buf, format='png')
            buf.seek(0)
            file = nextcord.File(buf, "activity_graph.png")
            embed.set_image(url="attachment://activity_graph.png")
            await channel.send(embed=embed, file=file)
        else:
            await channel.send(embed=embed)

    async def generate_activity_graph(self, report: Dict):
        """Generate activity visualization graph"""
        try:
            # Create figure
            plt.figure(figsize=(10, 6))
            plt.style.use('seaborn')

            # Get metrics for the report period
            metrics = await self.metrics.find({
                "guild_id": report["guild_id"],
                "timestamp": {
                    "$gte": datetime.combine(report["date"], datetime.min.time())
                }
            }).to_list(length=None)

            if not metrics:
                return None

            # Convert to DataFrame
            df = pd.DataFrame(metrics)
            
            # Plot member count and online count
            plt.plot(
                df["timestamp"],
                df["member_count"],
                label="Total Members",
                color="blue"
            )
            plt.plot(
                df["timestamp"],
                df["online_count"],
                label="Online Members",
                color="green"
            )

            plt.title("Member Activity Over Time")
            plt.xlabel("Time")
            plt.ylabel("Member Count")
            plt.legend()
            plt.xticks(rotation=45)
            plt.tight_layout()

            return plt.gcf()

        except Exception as e:
            logger.error(f"Error generating activity graph: {str(e)}")
            return None

    @commands.group(invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def analytics(self, ctx):
        """Server analytics commands"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="📊 Analytics Commands",
                description="View server analytics and insights",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Available Commands",
                value="""
                `!analytics overview` - Get server overview
                `!analytics activity` - View activity patterns
                `!analytics roles` - Role distribution analysis
                `!analytics growth` - Member growth analysis
                `!analytics report` - Generate custom report
                """,
                inline=False
            )
            await ctx.send(embed=embed)

    @analytics.command(name="overview")
    @commands.has_permissions(administrator=True)
    async def analytics_overview(self, ctx):
        """Get server overview analytics"""
        try:
            # Get today's metrics
            today = datetime.utcnow().date()
            metrics = await self.metrics.find({
                "guild_id": str(ctx.guild.id),
                "timestamp": {
                    "$gte": datetime.combine(today, datetime.min.time())
                }
            }).to_list(length=None)

            if not metrics:
                await ctx.send("No analytics data available for today!")
                return

            # Calculate statistics
            current = metrics[-1]
            avg_online = sum(m["online_count"] for m in metrics) / len(metrics)
            
            embed = nextcord.Embed(
                title="📊 Server Overview",
                color=nextcord.Color.blue(),
                timestamp=current["timestamp"]
            )

            embed.add_field(
                name="Current Status",
                value=f"""
                Total Members: {current['member_count']}
                Online Members: {current['online_count']}
                Text Channels: {current['channel_counts']['text']}
                Voice Channels: {current['channel_counts']['voice']}
                Average Online Today: {avg_online:.0f}
                """,
                inline=False
            )

            # Top roles by member count
            top_roles = sorted(
                current["role_distribution"].items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]

            embed.add_field(
                name="Top Roles",
                value="\n".join(
                    f"{role}: {count} members"
                    for role, count in top_roles
                ),
                inline=False
            )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error generating overview: {str(e)}")
            await ctx.send("Error generating server overview!")

    @analytics.command(name="activity")
    @commands.has_permissions(administrator=True)
    async def analytics_activity(self, ctx):
        """View server activity patterns"""
        try:
            # Get last 7 days of metrics
            week_ago = datetime.utcnow() - timedelta(days=7)
            metrics = await self.metrics.find({
                "guild_id": str(ctx.guild.id),
                "timestamp": {"$gte": week_ago}
            }).to_list(length=None)

            if not metrics:
                await ctx.send("No activity data available!")
                return

            df = pd.DataFrame(metrics)
            df["hour"] = df["timestamp"].dt.hour
            df["day"] = df["timestamp"].dt.day_name()

            # Activity heatmap by hour and day
            activity_matrix = df.pivot_table(
                values="online_count",
                index="day",
                columns="hour",
                aggfunc="mean"
            )

            plt.figure(figsize=(12, 6))
            sns.heatmap(
                activity_matrix,
                cmap="YlOrRd",
                annot=True,
                fmt=".0f"
            )
            plt.title("Activity Heatmap by Day and Hour")
            plt.xlabel("Hour of Day")
            plt.ylabel("Day of Week")
            
            # Save plot to buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            
            # Create and send embed with plot
            embed = nextcord.Embed(
                title="📊 Activity Analysis",
                description="Server activity patterns over the last 7 days",
                color=nextcord.Color.blue()
            )

            # Add peak times
            peak_hours = df.groupby("hour")["online_count"].mean().nlargest(3)
            peak_days = df.groupby("day")["online_count"].mean().nlargest(3)

            embed.add_field(
                name="Peak Hours",
                value="\n".join(f"{hour}:00: {count:.0f} members"
                              for hour, count in peak_hours.items()),
                inline=False
            )

            embed.add_field(
                name="Most Active Days",
                value="\n".join(f"{day}: {count:.0f} members"
                              for day, count in peak_days.items()),
                inline=False
            )

            file = nextcord.File(buf, "activity_heatmap.png")
            embed.set_image(url="attachment://activity_heatmap.png")
            
            await ctx.send(embed=embed, file=file)

        except Exception as e:
            logger.error(f"Error generating activity analysis: {str(e)}")
            await ctx.send("Error generating activity analysis!")

    @analytics.command(name="roles")
    @commands.has_permissions(administrator=True)
    async def analytics_roles(self, ctx):
        """View role distribution and changes"""
        try:
            # Get role metrics for last 30 days
            month_ago = datetime.utcnow() - timedelta(days=30)
            metrics = await self.metrics.find({
                "guild_id": str(ctx.guild.id),
                "timestamp": {"$gte": month_ago}
            }).to_list(length=None)

            if not metrics:
                await ctx.send("No role data available!")
                return

            # Analyze role changes
            first = metrics[0]["role_distribution"]
            last = metrics[-1]["role_distribution"]
            
            changes = {}
            all_roles = set(first.keys()) | set(last.keys())
            
            for role in all_roles:
                start = first.get(role, 0)
                end = last.get(role, 0)
                changes[role] = {
                    "start": start,
                    "end": end,
                    "change": end - start,
                    "growth": (end - start) / start if start > 0 else float('inf')
                }

            # Create visualization
            plt.figure(figsize=(10, 6))
            roles = sorted(changes.items(), key=lambda x: x[1]["end"], reverse=True)[:10]
            
            names = [r[0] for r in roles]
            current = [r[1]["end"] for r in roles]
            previous = [r[1]["start"] for r in roles]

            x = range(len(names))
            width = 0.35

            plt.bar([i - width/2 for i in x], previous, width, label='30 Days Ago')
            plt.bar([i + width/2 for i in x], current, width, label='Current')
            
            plt.title("Top 10 Roles - Member Distribution")
            plt.xlabel("Roles")
            plt.ylabel("Members")
            plt.xticks(x, names, rotation=45)
            plt.legend()
            plt.tight_layout()

            # Save plot to buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)

            # Create and send embed
            embed = nextcord.Embed(
                title="📊 Role Analytics",
                description="Role distribution and changes over the last 30 days",
                color=nextcord.Color.blue()
            )

            # Add fastest growing roles
            growing = sorted(
                changes.items(),
                key=lambda x: x[1]["growth"],
                reverse=True
            )[:5]

            embed.add_field(
                name="Fastest Growing Roles",
                value="\n".join(
                    f"{role}: {data['change']:+d} members ({data['growth']:.1%})"
                    for role, data in growing if data['growth'] != float('inf')
                ),
                inline=False
            )

            file = nextcord.File(buf, "role_distribution.png")
            embed.set_image(url="attachment://role_distribution.png")
            
            await ctx.send(embed=embed, file=file)

        except Exception as e:
            logger.error(f"Error generating role analytics: {str(e)}")
            await ctx.send("Error generating role analytics!")

    @analytics.command(name="growth")
    @commands.has_permissions(administrator=True)
    async def analytics_growth(self, ctx, days: int = 30):
        """Analyze member growth patterns"""
        try:
            # Get metrics for specified period
            start_date = datetime.utcnow() - timedelta(days=days)
            metrics = await self.metrics.find({
                "guild_id": str(ctx.guild.id),
                "timestamp": {"$gte": start_date}
            }).to_list(length=None)

            if not metrics:
                await ctx.send(f"No data available for the last {days} days!")
                return

            # Create growth visualization
            df = pd.DataFrame(metrics)
            df["date"] = df["timestamp"].dt.date
            daily = df.groupby("date").agg({
                "member_count": ["first", "last", "mean"],
                "online_count": "mean"
            }).reset_index()

            # Calculate daily changes
            daily["member_change"] = daily["member_count"]["last"].diff()

            plt.figure(figsize=(12, 6))
            plt.plot(daily["date"], daily["member_count"]["last"], label="Total Members")
            plt.plot(daily["date"], daily["online_count"]["mean"], label="Avg. Online")
            
            plt.title(f"Member Growth Over {days} Days")
            plt.xlabel("Date")
            plt.ylabel("Members")
            plt.legend()
            plt.grid(True)
            plt.xticks(rotation=45)
            plt.tight_layout()

            # Save plot to buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)

            # Create and send embed
            embed = nextcord.Embed(
                title="📈 Growth Analytics",
                description=f"Member growth analysis for the last {days} days",
                color=nextcord.Color.blue()
            )

            # Calculate growth statistics
            total_growth = daily["member_count"]["last"].iloc[-1] - daily["member_count"]["first"].iloc[0]
            avg_daily_growth = total_growth / days
            growth_rate = (total_growth / daily["member_count"]["first"].iloc[0]) * 100

            embed.add_field(
                name="Growth Summary",
                value=f"""
                Total Growth: {total_growth:+d} members
                Average Daily Growth: {avg_daily_growth:.1f} members
                Growth Rate: {growth_rate:.1f}%
                Current Members: {daily["member_count"]["last"].iloc[-1]}
                Average Online: {daily["online_count"]["mean"].mean():.0f} members
                """,
                inline=False
            )

            file = nextcord.File(buf, "growth_chart.png")
            embed.set_image(url="attachment://growth_chart.png")
            
            await ctx.send(embed=embed, file=file)

        except Exception as e:
            logger.error(f"Error generating growth analytics: {str(e)}")
            await ctx.send("Error generating growth analytics!")

def setup(bot):
    """Setup the Analytics cog"""
    bot.add_cog(Analytics(bot))
    logger.info("Analytics cog loaded successfully")