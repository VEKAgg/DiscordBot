import discord
from discord import app_commands
from discord.ext import commands
from utils.database import Database
from utils.logger import setup_logger
import aiohttp
import os

logger = setup_logger()

class GitHub(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = Database.db
        self.github_token = os.getenv('GITHUB_TOKEN')
        self.headers = {
            'Authorization': f'token {self.github_token}',
            'Accept': 'application/vnd.github.v3+json'
        }

    @app_commands.command(name="github", description="Link a GitHub repository to the channel")
    @app_commands.describe(
        repo="Repository name (format: owner/repo)",
        events="Event types to track (comma-separated: push,pull_request,issues)"
    )
    @app_commands.default_permissions(manage_webhooks=True)
    async def link_repo(self, interaction: discord.Interaction, repo: str, events: str = "push,pull_request,issues"):
        await interaction.response.defer()
        
        try:
            # Validate repository format
            if '/' not in repo:
                await interaction.followup.send("Invalid repository format. Use 'owner/repo'")
                return

            # Create webhook for the channel
            webhook = await interaction.channel.create_webhook(name=f"GitHub-{repo}")

            # Store webhook and repository info
            await self.db.github_webhooks.insert_one({
                "guild_id": interaction.guild_id,
                "channel_id": interaction.channel_id,
                "repository": repo,
                "webhook_id": webhook.id,
                "webhook_url": webhook.url,
                "events": events.split(',')
            })

            embed = discord.Embed(
                title="GitHub Integration Setup",
                description=f"Successfully linked {repo} to this channel!",
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error setting up GitHub webhook: {str(e)}")
            await interaction.followup.send("An error occurred while setting up GitHub integration.")

    @app_commands.command(name="githubrepos", description="List linked GitHub repositories")
    async def list_repos(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            webhooks = await self.db.github_webhooks.find({
                "guild_id": interaction.guild_id
            }).to_list(length=None)

            if not webhooks:
                await interaction.followup.send("No GitHub repositories are linked to this server.")
                return

            embed = discord.Embed(
                title="Linked GitHub Repositories",
                color=discord.Color.blue()
            )

            for hook in webhooks:
                channel = self.bot.get_channel(hook["channel_id"])
                embed.add_field(
                    name=hook["repository"],
                    value=f"Channel: {channel.mention if channel else 'Unknown'}\n"
                          f"Events: {', '.join(hook['events'])}",
                    inline=False
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error listing GitHub repos: {str(e)}")
            await interaction.followup.send("An error occurred while fetching repository list.")

async def setup(bot: commands.Bot):
    await bot.add_cog(GitHub(bot)) 