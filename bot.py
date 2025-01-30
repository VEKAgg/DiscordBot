import nextcord
from nextcord.ext import commands
import motor.motor_asyncio
from aioredis import Redis
import yaml
import logging
import os

# Load configuration
with open("config.yaml") as f:
    config = yaml.safe_load(f)

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

class MyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mongo_client = None
        self.db = None
        self.redis = None

    async def setup_hook(self):
        # Initialize MongoDB
        self.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(config["mongodb_uri"])
        self.db = self.mongo_client[config["database_name"]]
        
        # Initialize Redis
        self.redis = await Redis.from_url(config["redis_uri"])
        
        # Load all cogs
        for cog in os.listdir("bot/cogs"):
            if cog.endswith(".py") and not cog.startswith("_"):
                try:
                    self.load_extension(f"bot.cogs.{cog[:-3]}")
                    logging.info(f"Loaded cog: {cog[:-3]}")
                except Exception as e:
                    logging.error(f"Failed to load cog {cog[:-3]}: {e}")

intents = nextcord.Intents.all()
bot = MyBot(command_prefix=config["prefix"], intents=intents)

@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=nextcord.Activity(
        type=nextcord.ActivityType.watching,
        name="your server 👀"
    ))

if __name__ == "__main__":
    bot.run(config["token"])
