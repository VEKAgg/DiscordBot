import nextcord
from nextcord.ext import commands, tasks
import logging
from datetime import datetime, timedelta
import aiohttp
import feedparser
import asyncio
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

logger = logging.getLogger('VEKA.jobs')

class Jobs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.mongo
        self.jobs = self.db.jobs
        self.job_alerts = self.db.job_alerts
        self.job_sources = {
            "Jobicy": "https://jobicy.com/api/v2/remote-jobs",
            "Open Skills": "https://api.openskills.dev/v1/jobs",
            "StackOverflow": "https://stackoverflow.com/jobs/feed",
            "RemoteOK": "https://remoteok.io/remote-jobs.rss",
            "WeWorkRemotely": "https://weworkremotely.com/categories/remote-programming-jobs.rss"
        }
        self.update_jobs.start()

    def cog_unload(self):
        self.update_jobs.cancel()

    @tasks.loop(hours=6)
    async def update_jobs(self):
        """Update job listings from various sources"""
        try:
            # Clear old listings
            week_ago = datetime.utcnow() - timedelta(days=7)
            await self.jobs.delete_many({"posted_at": {"$lt": week_ago}})

            # Fetch new listings
            for source, url in self.job_sources.items():
                try:
                    if source in ["Jobicy", "Open Skills"]:
                        await self.fetch_api_jobs(source, url)
                    else:
                        await self.fetch_rss_jobs(source, url)
                except Exception as e:
                    logger.error(f"Error fetching jobs from {source}: {str(e)}")
                await asyncio.sleep(5)  # Rate limiting

            # Process job alerts
            await self.process_job_alerts()
            
        except Exception as e:
            logger.error(f"Error in job update task: {str(e)}")

    async def fetch_api_jobs(self, source: str, url: str):
        """Fetch jobs from API sources"""
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    jobs = []
                    if source == "Jobicy":
                        jobs = self.parse_jobicy_jobs(data)
                    elif source == "Open Skills":
                        jobs = self.parse_openskills_jobs(data)

                    # Store jobs
                    if jobs:
                        await self.jobs.insert_many(jobs)

    def parse_jobicy_jobs(self, data: Dict) -> List[Dict]:
        """Parse jobs from Jobicy API"""
        jobs = []
        for item in data.get('jobs', []):
            job = {
                "title": item.get('title'),
                "company": item.get('company'),
                "location": item.get('location', 'Remote'),
                "description": item.get('description'),
                "url": item.get('url'),
                "salary": item.get('salary'),
                "tags": item.get('tags', []),
                "source": "Jobicy",
                "posted_at": datetime.fromisoformat(item.get('posted_at')),
                "created_at": datetime.utcnow()
            }
            jobs.append(job)
        return jobs

    def parse_openskills_jobs(self, data: Dict) -> List[Dict]:
        """Parse jobs from Open Skills API"""
        jobs = []
        for item in data.get('jobs', []):
            job = {
                "title": item.get('title'),
                "company": item.get('company_name'),
                "location": item.get('location', 'Remote'),
                "description": item.get('description'),
                "url": item.get('application_url'),
                "salary": item.get('salary_range'),
                "tags": item.get('skills', []),
                "source": "Open Skills",
                "posted_at": datetime.fromisoformat(item.get('posted_date')),
                "created_at": datetime.utcnow()
            }
            jobs.append(job)
        return jobs

    async def fetch_rss_jobs(self, source: str, url: str):
        """Fetch jobs from RSS feeds"""
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    content = await resp.text()
                    feed = feedparser.parse(content)
                    
                    jobs = []
                    for entry in feed.entries:
                        # Clean and extract text from HTML
                        soup = BeautifulSoup(entry.get('description', ''), 'html.parser')
                        description = soup.get_text()
                        
                        # Extract tags/skills from description
                        tags = self.extract_skills_from_description(description)
                        
                        job = {
                            "title": entry.get('title'),
                            "company": entry.get('author', 'Unknown'),
                            "location": "Remote",  # Most RSS feeds are for remote jobs
                            "description": description,
                            "url": entry.get('link'),
                            "tags": tags,
                            "source": source,
                            "posted_at": datetime(*entry.get('published_parsed')[:6]),
                            "created_at": datetime.utcnow()
                        }
                        jobs.append(job)

                    if jobs:
                        await self.jobs.insert_many(jobs)

    def extract_skills_from_description(self, description: str) -> List[str]:
        """Extract common programming skills from job description"""
        common_skills = [
            "python", "javascript", "java", "c++", "c#", "ruby", "php", "swift",
            "golang", "rust", "typescript", "react", "angular", "vue", "node.js",
            "django", "flask", "spring", "aws", "azure", "gcp", "docker", "kubernetes",
            "sql", "mongodb", "postgresql", "mysql", "redis", "graphql", "rest"
        ]
        
        description = description.lower()
        found_skills = []
        
        for skill in common_skills:
            if skill in description:
                found_skills.append(skill)
                
        return found_skills

    async def process_job_alerts(self):
        """Process job alerts and notify users"""
        async for alert in self.job_alerts.find({"active": True}):
            user_id = alert["user_id"]
            keywords = alert["keywords"]
            excluded = alert.get("excluded_keywords", [])
            min_salary = alert.get("min_salary")
            
            # Build query
            query = {
                "posted_at": {
                    "$gt": datetime.utcnow() - timedelta(hours=6)  # New jobs in last 6 hours
                }
            }
            
            # Add keyword filters
            if keywords:
                query["$or"] = [
                    {"title": {"$regex": keyword, "$options": "i"}} for keyword in keywords
                ]
            
            # Add salary filter if specified
            if min_salary:
                query["salary"] = {"$gte": min_salary}
            
            # Find matching jobs
            matching_jobs = await self.jobs.find(query).to_list(length=None)
            
            # Filter out jobs with excluded keywords
            if excluded:
                matching_jobs = [
                    job for job in matching_jobs
                    if not any(kw.lower() in job["title"].lower() for kw in excluded)
                ]
            
            if matching_jobs:
                user = self.bot.get_user(int(user_id))
                if user:
                    await self.send_job_alert(user, matching_jobs)

    async def send_job_alert(self, user: nextcord.User, jobs: List[Dict]):
        """Send job alert to user"""
        embed = nextcord.Embed(
            title="🔔 New Job Alerts",
            description=f"Found {len(jobs)} new jobs matching your criteria",
            color=nextcord.Color.blue()
        )

        for job in jobs[:5]:  # Show top 5 jobs
            embed.add_field(
                name=f"📋 {job['title']}",
                value=(
                    f"**Company:** {job['company']}\n"
                    f"**Location:** {job['location']}\n"
                    f"**Skills:** {', '.join(job['tags'][:5])}\n"
                    f"**Source:** {job['source']}\n"
                    f"[Apply Here]({job['url']})"
                ),
                inline=False
            )

        if len(jobs) > 5:
            embed.set_footer(text=f"Showing 5 of {len(jobs)} new jobs. Use !jobs search to see more.")

        try:
            await user.send(embed=embed)
        except nextcord.Forbidden:
            logger.warning(f"Could not send job alert to user {user.id}")

    @commands.group(invoke_without_command=True)
    async def jobs(self, ctx):
        """Job search and alert commands"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="💼 Job Search Commands",
                description="Find your next opportunity!",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Available Commands",
                value="""
                `!jobs search <keywords>` - Search for jobs
                `!jobs alert add <keywords>` - Create job alert
                `!jobs alert remove` - Remove job alert
                `!jobs alert list` - List your job alerts
                `!jobs sources` - List job sources
                `!jobs latest` - Show latest jobs
                """,
                inline=False
            )
            await ctx.send(embed=embed)

    @jobs.command(name="search")
    async def jobs_search(self, ctx, *, keywords: str):
        """Search for jobs matching keywords"""
        keywords = [k.strip() for k in keywords.split(',')]
        
        query = {
            "$or": [
                {"title": {"$regex": keyword, "$options": "i"}} for keyword in keywords
            ]
        }
        
        matching_jobs = await self.jobs.find(query).sort(
            "posted_at", -1
        ).limit(10).to_list(length=None)
        
        if not matching_jobs:
            await ctx.send(f"No jobs found matching: {', '.join(keywords)}")
            return

        embed = nextcord.Embed(
            title="🔍 Job Search Results",
            description=f"Found {len(matching_jobs)} jobs matching: {', '.join(keywords)}",
            color=nextcord.Color.blue()
        )

        for job in matching_jobs:
            embed.add_field(
                name=f"📋 {job['title']}",
                value=(
                    f"**Company:** {job['company']}\n"
                    f"**Location:** {job['location']}\n"
                    f"**Skills:** {', '.join(job['tags'][:5])}\n"
                    f"**Posted:** {job['posted_at'].strftime('%Y-%m-%d')}\n"
                    f"[Apply Here]({job['url']})"
                ),
                inline=False
            )

        await ctx.send(embed=embed)

    @jobs.group(name="alert")
    async def jobs_alert(self, ctx):
        """Manage job alerts"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `!jobs alert add/remove/list` to manage your job alerts")

    @jobs_alert.command(name="add")
    async def alert_add(self, ctx):
        """Create a new job alert"""
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            # Get keywords
            await ctx.send("Enter keywords for your job alert (comma-separated):")
            msg = await self.bot.wait_for('message', timeout=30.0, check=check)
            keywords = [k.strip() for k in msg.content.split(',')]

            # Get excluded keywords (optional)
            await ctx.send("Enter keywords to exclude (comma-separated, or 'skip'):")
            msg = await self.bot.wait_for('message', timeout=30.0, check=check)
            excluded = []
            if msg.content.lower() != 'skip':
                excluded = [k.strip() for k in msg.content.split(',')]

            # Get minimum salary (optional)
            await ctx.send("Enter minimum salary (or 'skip'):")
            msg = await self.bot.wait_for('message', timeout=30.0, check=check)
            min_salary = None
            if msg.content.lower() != 'skip':
                try:
                    min_salary = int(msg.content)
                except ValueError:
                    await ctx.send("Invalid salary format, skipping salary filter.")

            # Create alert
            alert = {
                "user_id": str(ctx.author.id),
                "keywords": keywords,
                "excluded_keywords": excluded,
                "min_salary": min_salary,
                "active": True,
                "created_at": datetime.utcnow()
            }
            
            await self.job_alerts.update_one(
                {"user_id": str(ctx.author.id)},
                {"$set": alert},
                upsert=True
            )

            embed = nextcord.Embed(
                title="✅ Job Alert Created",
                description="You'll receive notifications for new matching jobs",
                color=nextcord.Color.green()
            )
            embed.add_field(name="Keywords", value=", ".join(keywords), inline=False)
            if excluded:
                embed.add_field(name="Excluded Keywords", value=", ".join(excluded), inline=False)
            if min_salary:
                embed.add_field(name="Minimum Salary", value=f"${min_salary:,}", inline=False)
            
            await ctx.send(embed=embed)

        except asyncio.TimeoutError:
            await ctx.send("❌ Alert creation timed out. Please try again.")

    @jobs_alert.command(name="remove")
    async def alert_remove(self, ctx):
        """Remove your job alert"""
        result = await self.job_alerts.delete_one({"user_id": str(ctx.author.id)})
        if result.deleted_count > 0:
            await ctx.send("✅ Your job alert has been removed.")
        else:
            await ctx.send("You don't have any active job alerts.")

    @jobs_alert.command(name="list")
    async def alert_list(self, ctx):
        """List your job alerts"""
        alert = await self.job_alerts.find_one({"user_id": str(ctx.author.id)})
        if not alert:
            await ctx.send("You don't have any active job alerts.")
            return

        embed = nextcord.Embed(
            title="📋 Your Job Alerts",
            color=nextcord.Color.blue()
        )
        embed.add_field(name="Keywords", value=", ".join(alert["keywords"]), inline=False)
        if alert.get("excluded_keywords"):
            embed.add_field(
                name="Excluded Keywords",
                value=", ".join(alert["excluded_keywords"]),
                inline=False
            )
        if alert.get("min_salary"):
            embed.add_field(name="Minimum Salary", value=f"${alert['min_salary']:,}", inline=False)
        
        await ctx.send(embed=embed)

    @jobs.command(name="latest")
    async def jobs_latest(self, ctx):
        """Show latest job postings"""
        latest_jobs = await self.jobs.find().sort(
            "posted_at", -1
        ).limit(5).to_list(length=None)

        if not latest_jobs:
            await ctx.send("No recent job postings found.")
            return

        embed = nextcord.Embed(
            title="📢 Latest Job Postings",
            color=nextcord.Color.blue()
        )

        for job in latest_jobs:
            embed.add_field(
                name=f"📋 {job['title']}",
                value=(
                    f"**Company:** {job['company']}\n"
                    f"**Location:** {job['location']}\n"
                    f"**Skills:** {', '.join(job['tags'][:5])}\n"
                    f"**Posted:** {job['posted_at'].strftime('%Y-%m-%d')}\n"
                    f"[Apply Here]({job['url']})"
                ),
                inline=False
            )

        await ctx.send(embed=embed)

    @jobs.command(name="sources")
    async def jobs_sources(self, ctx):
        """List all job sources"""
        embed = nextcord.Embed(
            title="📚 Job Sources",
            description="Current sources for job listings:",
            color=nextcord.Color.blue()
        )

        for source in self.job_sources.keys():
            count = await self.jobs.count_documents({"source": source})
            embed.add_field(
                name=source,
                value=f"Active listings: {count}",
                inline=True
            )

        await ctx.send(embed=embed)

def setup(bot):
    """Setup the Jobs cog"""
    bot.add_cog(Jobs(bot))
    logger.info("Jobs cog loaded successfully")