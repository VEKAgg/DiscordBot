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

# Access Control — comma-separated Discord user IDs
ADMIN_IDS = [int(item) for item in os.getenv('ADMIN_IDS', '').split(',') if item.strip().isdigit()]
OWNER_IDS = [int(item) for item in os.getenv('OWNER_IDS', '').split(',') if item.strip().isdigit()]
FOUNDER_IDS = [int(item) for item in os.getenv('FOUNDER_IDS', '').split(',') if item.strip().isdigit()]
STAFF_IDS = [int(item) for item in os.getenv('STAFF_IDS', '').split(',') if item.strip().isdigit()]
INTERN_IDS = [int(item) for item in os.getenv('INTERN_IDS', '').split(',') if item.strip().isdigit()]
DONATOR_IDS = [int(item) for item in os.getenv('DONATOR_IDS', '').split(',') if item.strip().isdigit()]
ACTIVE_PRO_IDS = [int(item) for item in os.getenv('ACTIVE_PRO_IDS', '').split(',') if item.strip().isdigit()]

# Channel IDs
_admin_alert_channel = os.getenv('ADMIN_ALERT_CHANNEL_ID', '')
ADMIN_ALERT_CHANNEL_ID = int(_admin_alert_channel) if _admin_alert_channel.strip().isdigit() else None

STAFF_BOT_COMMANDS_CHANNEL_ID = 1328775724668031126
STAFF_CHANNEL_ID = 1091908318324334704
PUBLIC_BOT_COMMANDS_CHANNEL_ID = 1385610318889222226

# Notification settings
NOTIFICATION_SQUAD_ROLE_NAME = 'notification squad'
DAILY_BUMP_HOUR = 18  # 6 PM
DAILY_BUMP_MINUTE = 0
IST_UTC_OFFSET = 5.5  # IST is UTC+5:30

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

# --- Radio Configuration ---
RADIO_STREAM_URL = os.getenv('RADIO_STREAM_URL', 'https://www.youtube.com/watch?v=jfKfPfyJRdk')
_radio_channel = os.getenv('RADIO_VOICE_CHANNEL_ID', '')
RADIO_VOICE_CHANNEL_ID = int(_radio_channel) if _radio_channel.strip().isdigit() else None
RADIO_REFRESH_INTERVAL = 7200  # seconds (2 hours) — refresh stream URL before YouTube expiry
RADIO_STABILITY_INTERVAL = 30  # seconds between stability checks
RADIO_RECOVERY_PINGS_REQUIRED = 3  # consecutive healthy checks before rejoining

# --- RPG / Leaderboard Configuration ---
_leaderboard_channel = os.getenv('LEADERBOARD_CHANNEL_ID', '')
LEADERBOARD_CHANNEL_ID = int(_leaderboard_channel) if _leaderboard_channel.strip().isdigit() else None
LEADERBOARD_UPDATE_INTERVAL = 1800  # seconds (30 minutes)
LEADERBOARD_TOP_N = 10
MESSAGE_XP_COOLDOWN = 10  # seconds between message XP awards

RPG_POINTS: dict[str, int] = {
    'message': 1,
    'command': 2,
    'voice_per_minute': 1,
    'daily_claim': 5,
}

XP_MULTIPLIERS: dict[str, float] = {
    'donator': 1.2,
    'active_pro': 1.1,
}

# Activity roles — dynamic, auto-assigned/removed based on activity thresholds
ACTIVITY_ROLES: dict[str, int] = {
    'active_member': 100,  # role name: 'Active Member'
    'active_plus': 500,  # role name: 'Active+'
    'active_star': 2000,  # role name: 'Active Star'
}
ACTIVITY_ROLE_INACTIVITY_DAYS = 14
