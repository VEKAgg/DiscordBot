import os

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot Configuration
BOT_PREFIX = '!'
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
BOT_VERSION = os.getenv('BOT_VERSION', '1.0.0')
ENVIRONMENT = os.getenv('ENVIRONMENT', os.getenv('BOT_ENVIRONMENT', 'development'))
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
ADMIN_IDS = [int(item) for item in os.getenv('ADMIN_IDS', '').split(',') if item.strip().isdigit()]
OWNER_IDS = [int(item) for item in os.getenv('OWNER_IDS', '').split(',') if item.strip().isdigit()]

_admin_alert_channel = os.getenv('ADMIN_ALERT_CHANNEL_ID', '')
ADMIN_ALERT_CHANNEL_ID = int(_admin_alert_channel) if _admin_alert_channel.strip().isdigit() else None

# PostgreSQL Configuration
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = os.getenv('POSTGRES_PORT', '5432')
POSTGRES_DB = os.getenv('POSTGRES_DB', 'veka_bot')
POSTGRES_USER = os.getenv('POSTGRES_USER', 'veka_bot_user')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'example')
DATABASE_URL = os.getenv('DATABASE_URL') or (
    f'postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}'
)

# Mentorship Configuration
MENTORSHIP_CATEGORIES: list[str] = ['programming', 'design', 'career', 'devops', 'data_science', 'other']
MENTORSHIP_ROLES: dict[str, str] = {'mentor': 'Mentor', 'mentee': 'Mentee'}
POINTS_CONFIG: dict[str, int] = {'mentor_session': 50, 'mentee_completion': 25, 'first_mentorship': 100}

# RSS Feed Configuration
RSS_FEEDS = {
    'tech_news': [
        'https://feeds.feedburner.com/TechCrunch',
        'https://www.wired.com/feed/rss',
        'https://www.theverge.com/rss/index.xml',
    ],
    'job_listings': [
        'https://stackoverflow.com/jobs/feed',
        'https://remoteok.io/remote-jobs.rss',
        'https://weworkremotely.com/categories/remote-programming-jobs.rss',
    ],
    'dev_blogs': ['https://dev.to/feed', 'https://medium.com/feed/tag/programming', 'https://blog.github.com/all.atom'],
}

# API Rate Limits (requests per minute)
RATE_LIMITS = {'rss_fetch': 5, 'github_api': 60}
