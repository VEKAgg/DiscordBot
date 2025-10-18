# Profile System Constants
SKILL_CATEGORIES = [
    "Programming Languages",
    "Web Development",
    "Mobile Development",
    "DevOps & Cloud",
    "Data Science & ML",
    "Databases",
    "System Design",
    "Soft Skills"
]

LOOKING_FOR_OPTIONS = [
    "Full-time Job",
    "Internship",
    "Mentorship",
    "Project Collaboration",
    "Technical Discussions",
    "Professional Network"
]

PRIVACY_LEVELS = {
    "PUBLIC": "Available to everyone",
    "CONNECTIONS": "Only visible to your connections",
    "PRIVATE": "Only visible to you"
}

PROFILE_FIELD_DEFAULTS = {
    "name": "PUBLIC",
    "bio": "PUBLIC",
    "grad_year": "PUBLIC",
    "skills": "PUBLIC",
    "looking_for": "PUBLIC",
    "github": "CONNECTIONS",
    "leetcode": "CONNECTIONS",
    "email": "PRIVATE",
    "location": "CONNECTIONS"
}

# Leaderboard Categories
LEADERBOARD_CATEGORIES = [
    "connections",
    "endorsements",
    "events",
    "mentoring",
    "activity"
]

# Job Board Constants
JOB_SOURCES = [
    "Jobicy",
    "RemoteOK",
    "GitHub Jobs",
    "Stack Overflow Jobs",
    "We Work Remotely"
]

JOB_TYPES = [
    "Full-time",
    "Part-time",
    "Contract",
    "Internship",
    "Remote",
    "Hybrid",
    "Onsite"
]

JOB_CATEGORIES = [
    "Software Development",
    "DevOps & SRE",
    "Data Science & Analytics",
    "Product Management",
    "UX/UI Design",
    "Technical Writing",
    "QA & Testing",
    "IT & Support"
]

# Event Constants
EVENT_TYPES = [
    "Workshop",
    "Tech Talk",
    "AMA Session",
    "Project Demo",
    "Hackathon",
    "Study Group",
    "Networking",
    "Career Fair"
]

LOCATION_RADIUS_OPTIONS = [
    25,   # Local
    50,   # City-wide
    100,  # Regional
    500   # National
]

# Rate Limiting Tiers
RATE_LIMIT_TIERS = {
    "light": {
        "limit": None,  # No cooldown
        "paid_limit": None
    },
    "medium": {
        "limit": 50,    # Per day
        "paid_limit": 100
    },
    "heavy": {
        "limit": 5,     # Per hour
        "paid_limit": 10
    }
}

# Command Categories
COMMAND_CATEGORIES = {
    "profile": "light",
    "connect": "medium",
    "recommend": "medium",
    "event_create": "heavy",
    "job_post": "heavy",
    "mentorship_request": "medium"
}

# Activity Tracking
INACTIVITY_TIERS = [
    {
        "days": 7,
        "message": "Hey! Haven't seen you in a while. Hope you're doing well!"
    },
    {
        "days": 14,
        "message": "Missing your contributions to our community! Drop by when you can."
    },
    {
        "days": 21,
        "message": "Just checking in - we'd love to have you back in the community!"
    }
]

DM_TYPES = [
    "connection_requests",
    "event_reminders",
    "job_alerts",
    "skill_endorsements",
    "inactivity_notices",
    "milestone_updates"
]

# Bot Configuration
DEFAULT_PREFIX = "!"
COMMAND_TIMEOUT = 30  # seconds
API_TIMEOUT = 10     # seconds
CACHE_TTL = 3600    # 1 hour

# Redis Keys
REDIS_KEYS = {
    "presence": "presence:{user_id}",
    "messages": "messages:{user_id}",
    "commands": "commands:{user_id}",
    "activity": "activity:{user_id}",
    "leaderboard": "leaderboard:{category}",
    "job_cache": "job_cache:{source}",
    "event_cache": "event_cache:{location}"
}

# MongoDB Collections
MONGO_COLLECTIONS = [
    "profiles",
    "connections",
    "endorsements",
    "activities",
    "events",
    "jobs",
    "workshops",
    "mentorships",
    "analytics",
    "oauth_tokens",
    "user_settings",
    "guild_settings",
    "scheduled_tasks"
]

# Error Messages
ERROR_MESSAGES = {
    "profile_not_found": "Please create your profile first using /profile create",
    "not_authorized": "You don't have permission to perform this action",
    "rate_limited": "You've reached the rate limit for this command",
    "invalid_input": "Please check your input and try again",
    "api_error": "An error occurred while processing your request",
    "missing_permissions": "Bot is missing required permissions",
    "feature_disabled": "This feature is currently disabled",
    "maintenance_mode": "Bot is currently in maintenance mode"
}