"""
Audit Logging System
Tracks all important actions for security and compliance
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any
from src.database.database import db

logger = logging.getLogger('VEKA.security.audit')

class AuditLogger:
    """
    Logs security-relevant events to database
    
    Usage:
        await audit_log.record(
            user_id="123456789",
            action="marketplace_item_created",
            details={"item_id": "abc123", "price": 99.99}
        )
    """
    
    def __init__(self):
        self.enabled = True
    
    async def record(
        self,
        user_id: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
        guild_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        severity: str = 'info'
    ):
        """
        Record an audit log entry
        
        Args:
            user_id: Discord user ID
            action: Action performed (e.g., 'command_used', 'item_purchased')
            details: Additional context (dict)
            guild_id: Discord guild ID (optional)
            channel_id: Discord channel ID (optional)
            severity: 'info', 'warning', 'critical'
        """
        if not self.enabled:
            return
        
        try:
            import json
            details_json = json.dumps(details) if details else None
            
            await db.execute(
                """INSERT INTO audit_logs 
                   (user_id, action, details, guild_id, channel_id, severity, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                user_id, action, details_json, guild_id, channel_id, 
                severity, datetime.utcnow()
            )
            
            # Also log to file for immediate visibility
            log_message = f"AUDIT: {action} by user {user_id}"
            if severity == 'critical':
                logger.critical(log_message)
            elif severity == 'warning':
                logger.warning(log_message)
            else:
                logger.info(log_message)
                
        except Exception as e:
            logger.error(f"Failed to record audit log: {str(e)}")
    
    async def get_recent(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
        hours: Optional[int] = None
    ) -> list:
        """
        Get recent audit log entries
        
        Args:
            user_id: Filter by user
            action: Filter by action type
            limit: Max number of results
            hours: Only return entries from last N hours
        """
        query = "SELECT * FROM audit_logs WHERE 1=1"
        params = []
        param_count = 0
        
        if user_id:
            param_count += 1
            query += f" AND user_id = ${param_count}"
            params.append(user_id)
        
        if action:
            param_count += 1
            query += f" AND action = ${param_count}"
            params.append(action)
        
        if hours:
            param_count += 1
            query += f" AND created_at > NOW() - INTERVAL '${param_count} hours'"
            params.append(hours)
        
        query += " ORDER BY created_at DESC"
        query += f" LIMIT ${param_count + 1}"
        params.append(limit)
        
        return await db.fetch_many(query, *params)
    
    async def get_user_actions(self, user_id: str, hours: int = 24) -> Dict[str, int]:
        """Get count of actions by user in last N hours"""
        results = await db.fetch_many(
            """SELECT action, COUNT(*) as count 
               FROM audit_logs 
               WHERE user_id = $1 
               AND created_at > NOW() - INTERVAL '$2 hours'
               GROUP BY action""",
            user_id, hours
        )
        
        return {row['action']: row['count'] for row in results}
    
    async def detect_suspicious_activity(self, user_id: str) -> bool:
        """
        Detect suspicious patterns in user activity
        
        Returns True if suspicious activity detected
        """
        # Check for rapid command execution
        recent_commands = await db.fetch_one(
            """SELECT COUNT(*) as count 
               FROM audit_logs 
               WHERE user_id = $1 
               AND action LIKE 'command_%'
               AND created_at > NOW() - INTERVAL '1 minute'""",
            user_id
        )
        
        if recent_commands and recent_commands['count'] > 20:
            await self.record(
                user_id=user_id,
                action='suspicious_activity_detected',
                details={'reason': 'excessive_commands', 'count': recent_commands['count']},
                severity='warning'
            )
            return True
        
        # Check for marketplace fraud patterns
        recent_transactions = await db.fetch_one(
            """SELECT COUNT(*) as count 
               FROM audit_logs 
               WHERE user_id = $1 
               AND action IN ('marketplace_item_created', 'marketplace_item_purchased')
               AND created_at > NOW() - INTERVAL '1 hour'""",
            user_id
        )
        
        if recent_transactions and recent_transactions['count'] > 10:
            await self.record(
                user_id=user_id,
                action='suspicious_activity_detected',
                details={'reason': 'excessive_marketplace_activity', 'count': recent_transactions['count']},
                severity='warning'
            )
            return True
        
        return False

# Global audit logger instance
audit_log = AuditLogger()

# Decorator for automatic audit logging
from functools import wraps

def audit_action(action_name: str, include_args: bool = True):
    """
    Decorator to automatically log command execution
    
    Usage:
        @audit_action('quiz_completed')
        @commands.command()
        async def quiz(self, ctx):
            pass
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get context
            ctx = args[1] if len(args) > 1 else kwargs.get('ctx')
            
            result = await func(*args, **kwargs)
            
            if ctx:
                details = {}
                if include_args and ctx.args:
                    details['args'] = str(ctx.args)
                
                await audit_log.record(
                    user_id=str(ctx.author.id),
                    action=action_name,
                    details=details,
                    guild_id=str(ctx.guild.id) if ctx.guild else None,
                    channel_id=str(ctx.channel.id)
                )
            
            return result
        return wrapper
    return decorator
