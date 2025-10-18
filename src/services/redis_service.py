import redis.asyncio as redis
import json
import datetime
from typing import Any, Optional, Union, Dict
from ..config.config import Config
from ..utils.constants.bot_constants import REDIS_KEYS

class RedisService:
    def __init__(self):
        self.config = Config()
        self.redis = redis.Redis(
            host=self.config.get("redis_host", "localhost"),
            port=self.config.get("redis_port", 6379),
            db=self.config.get("redis_db", 0),
            decode_responses=True
        )

    async def set(
        self,
        key: str,
        value: Union[str, dict, list],
        expiry: Optional[int] = None
    ) -> bool:
        """Set a key-value pair in Redis"""
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            await self.redis.set(key, value, ex=expiry)
            return True
        except Exception as e:
            print(f"Redis set error: {e}")
            return False

    async def get(self, key: str) -> Optional[Any]:
        """Get a value from Redis"""
        try:
            value = await self.redis.get(key)
            if not value:
                return None
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        except Exception as e:
            print(f"Redis get error: {e}")
            return None

    async def delete(self, key: str) -> bool:
        """Delete a key from Redis"""
        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            print(f"Redis delete error: {e}")
            return False

    async def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """Increment a counter in Redis"""
        try:
            return await self.redis.incr(key, amount)
        except Exception as e:
            print(f"Redis increment error: {e}")
            return None

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiry on a key"""
        try:
            return await self.redis.expire(key, seconds)
        except Exception as e:
            print(f"Redis expire error: {e}")
            return False

    # Activity Tracking Methods
    async def update_presence(self, user_id: int, status: str) -> bool:
        """Update user presence in Redis"""
        key = REDIS_KEYS["presence"].format(user_id=user_id)
        data = {
            "status": status,
            "last_seen": datetime.datetime.utcnow().isoformat(),
            "updated_at": datetime.datetime.utcnow().isoformat()
        }
        return await self.set(key, data, expiry=86400 * 30)  # 30 days TTL

    async def increment_messages(self, user_id: int) -> Optional[int]:
        """Increment user message counter"""
        key = REDIS_KEYS["messages"].format(user_id=user_id)
        count = await self.increment(key)
        if count == 1:  # First message, set expiry
            await self.expire(key, 86400 * 7)  # 7 days TTL
        return count

    async def track_command(self, user_id: int, command: str) -> bool:
        """Track command usage"""
        key = REDIS_KEYS["commands"].format(user_id=user_id)
        data = await self.get(key) or {}
        data[command] = data.get(command, 0) + 1
        return await self.set(key, data, expiry=86400)  # 1 day TTL

    # Rate Limiting Methods
    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window: int
    ) -> tuple[bool, Optional[int]]:
        """Check if action is rate limited"""
        try:
            current = await self.increment(key)
            if current == 1:  # First request in window
                await self.expire(key, window)
            
            remaining = limit - current if current <= limit else 0
            return current <= limit, remaining
        except Exception as e:
            print(f"Rate limit check error: {e}")
            return False, None

    # Caching Methods
    async def cache_job_data(self, source: str, jobs: list) -> bool:
        """Cache job listings"""
        key = REDIS_KEYS["job_cache"].format(source=source)
        return await self.set(key, jobs, expiry=21600)  # 6 hours TTL

    async def cache_event_data(self, location: str, events: list) -> bool:
        """Cache events data"""
        key = REDIS_KEYS["event_cache"].format(location=location)
        return await self.set(key, events, expiry=86400)  # 24 hours TTL

    async def update_leaderboard(self, category: str, data: list) -> bool:
        """Update leaderboard data"""
        key = REDIS_KEYS["leaderboard"].format(category=category)
        return await self.set(key, data, expiry=3600)  # 1 hour TTL

    # User Activity Methods
    async def get_active_users(self, hours: int = 24) -> list:
        """Get list of active users in last N hours"""
        active_users = []
        async for key in self.redis.scan_iter(match=REDIS_KEYS["presence"].format(user_id="*")):
            data = await self.get(key)
            if data:
                last_seen = datetime.datetime.fromisoformat(data["last_seen"])
                if (datetime.datetime.utcnow() - last_seen).total_seconds() <= hours * 3600:
                    user_id = int(key.split(":")[-1])
                    active_users.append({
                        "user_id": user_id,
                        "status": data["status"],
                        "last_seen": last_seen
                    })
        return active_users

    async def get_user_stats(self, user_id: int) -> Dict:
        """Get comprehensive user activity stats"""
        presence_key = REDIS_KEYS["presence"].format(user_id=user_id)
        messages_key = REDIS_KEYS["messages"].format(user_id=user_id)
        commands_key = REDIS_KEYS["commands"].format(user_id=user_id)
        
        presence = await self.get(presence_key) or {}
        message_count = int(await self.get(messages_key) or 0)
        commands = await self.get(commands_key) or {}
        
        return {
            "status": presence.get("status", "offline"),
            "last_seen": presence.get("last_seen"),
            "message_count": message_count,
            "command_usage": commands
        }

    # Cleanup Methods
    async def cleanup_expired_data(self) -> bool:
        """Clean up any expired data that Redis hasn't auto-removed"""
        try:
            # Clean up presence data older than 30 days
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=30)
            async for key in self.redis.scan_iter(match=REDIS_KEYS["presence"].format(user_id="*")):
                data = await self.get(key)
                if data and datetime.datetime.fromisoformat(data["updated_at"]) < cutoff:
                    await self.delete(key)
            
            # Clean up other expired data
            # Add more cleanup logic as needed
            
            return True
        except Exception as e:
            print(f"Redis cleanup error: {e}")
            return False