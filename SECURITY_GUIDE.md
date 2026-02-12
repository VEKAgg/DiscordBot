# Security Implementation Guide

## Overview

Security features have been implemented for the VEKA Discord Bot. This guide explains how to use them.

## Security Components

### 1. Rate Limiting (`src/utils/security/rate_limiter.py`)

Prevents command spam by limiting how often users can execute commands.

**Usage in commands:**

```python
from src.utils.security import rate_limit

class MyCog(commands.Cog):
    @rate_limit('quiz')  # Uses 'quiz' rate limit rules
    @commands.command()
    async def quiz(self, ctx):
        # Command logic here
        pass
```

**Default Rate Limits:**
- `default`: 5 commands per 60 seconds
- `quiz`: 3 attempts per 60 seconds  
- `marketplace`: 2 posts per 5 minutes
- `mentorship`: 5 actions per 5 minutes
- `admin`: 10 commands per 60 seconds

**Manual rate limit check:**
```python
from src.utils.security import rate_limiter

is_limited, retry_after = await rate_limiter.is_rate_limited(user_id, 'quiz')
```

---

### 2. Input Validation (`src/utils/security/validation.py`)

Sanitizes user input to prevent injection attacks.

**Available validators:**

```python
from src.utils.security import InputValidator, sanitize, is_safe

# Sanitize text
safe_text = InputValidator.sanitize_text(user_input, max_length=1000)

# Validate Discord ID
is_valid = InputValidator.validate_discord_id(user_id)

# Validate URL
is_valid = InputValidator.validate_url(url)

# Check for profanity
has_bad_words = InputValidator.contains_profanity(text)

# Check for spam
is_spam = InputValidator.is_spam(text, threshold=0.7)

# Validate marketplace item
result = InputValidator.validate_marketplace_item(title, description, price)
if not result['valid']:
    errors = result['errors']

# Quick sanitize
safe = sanitize(dirty_text)

# Quick safety check
if not is_safe(text):
    await ctx.send("Inappropriate content detected!")
```

---

### 3. Audit Logging (`src/utils/security/audit.py`)

Records all security-relevant actions for monitoring and compliance.

**Database Schema:**
- `audit_logs` table stores user actions
- `user_security` table tracks warnings/blocks
- `security_events` table stores blocked users

**Usage:**

```python
from src.utils.security import audit_log, audit_action

# Automatic logging with decorator
@audit_action('quiz_completed')
@commands.command()
async def quiz(self, ctx):
    # This action will be automatically logged
    pass

# Manual logging
await audit_log.record(
    user_id=str(ctx.author.id),
    action='marketplace_item_created',
    details={'item_id': item_id, 'price': price},
    guild_id=str(ctx.guild.id),
    channel_id=str(ctx.channel.id)
)

# Detect suspicious activity
is_suspicious = await audit_log.detect_suspicious_activity(user_id)
if is_suspicious:
    # Take action
    pass
```

**View recent logs:**
```python
logs = await audit_log.get_recent(user_id=user_id, limit=50)
```

---

### 4. Role-Based Access Control (`src/utils/security/rbac.py`)

Manages permissions based on Discord roles.

**Role Hierarchy:**
1. `USER` - Basic commands only
2. `VERIFIED` - Can use marketplace
3. `MODERATOR` - Can kick/ban/mute
4. `ADMIN` - Can manage bot settings
5. `OWNER` - Full access

**Discord Role Mapping:**
- `everyone` → USER
- `verified` → VERIFIED
- `mod/moderator` → MODERATOR
- `admin/administrator` → ADMIN
- `owner` → OWNER
- Guild owner → OWNER

**Usage:**

```python
from src.utils.security import require_mod, require_admin, require_verified, rbac, Role

# Require specific role level
@require_mod()
@commands.command()
async def kick(self, ctx, member: nextcord.Member):
    # Only moderators and above can use this
    pass

@require_admin()
@commands.command()
async def config(self, ctx):
    # Only admins and above can use this
    pass

@require_verified()
@commands.command()
async def sell(self, ctx):
    # Only verified users and above can use this
    pass

# Check permission manually
user_role = rbac.get_user_role(ctx)
if rbac.has_permission(user_role, 'marketplace'):
    # Allow marketplace access
    pass
```

---

## Security Best Practices

### 1. Always Validate Input

```python
@commands.command()
async def search(self, ctx, *, query: str):
    # Sanitize input
    safe_query = sanitize(query)
    
    # Check for inappropriate content
    if not is_safe(safe_query):
        await ctx.send("❌ Search query contains inappropriate content.")
        return
    
    # Proceed with search
```

### 2. Combine Security Features

```python
from src.utils.security import rate_limit, require_verified, audit_action, sanitize

class MarketplaceCog(commands.Cog):
    @rate_limit('marketplace')
    @require_verified()
    @audit_action('marketplace_item_created')
    @commands.command()
    async def sell(self, ctx, title: str, price: str, *, description: str):
        # Validate inputs
        safe_title = sanitize(title, max_length=100)
        safe_desc = sanitize(description, max_length=1000)
        
        # Validate price
        price_val = InputValidator.validate_price(price)
        if price_val is None:
            await ctx.send("❌ Invalid price format.")
            return
        
        # Validate marketplace item
        result = InputValidator.validate_marketplace_item(safe_title, safe_desc, price_val)
        if not result['valid']:
            await ctx.send(f"❌ {', '.join(result['errors'])}")
            return
        
        # Check for suspicious activity
        is_suspicious = await audit_log.detect_suspicious_activity(str(ctx.author.id))
        if is_suspicious:
            await ctx.send("❌ Unusual activity detected. Please contact a moderator.")
            return
        
        # Create listing
        # ... your logic here
```

### 3. Log All Important Actions

```python
# Log security events
await audit_log.record(
    user_id=str(ctx.author.id),
    action='user_warned',
    details={'reason': 'spam', 'message_count': 10},
    severity='warning'
)

# Log critical events
await audit_log.record(
    user_id=str(ctx.author.id),
    action='user_banned',
    details={'reason': 'harassment', 'evidence': 'message_id_123'},
    severity='critical'
)
```

---

## Database Migrations

Run the security schema migration:

```bash
psql -h localhost -U veka_user -d veka_bot -f migrations/003_security_schema.sql
```

This creates:
- `audit_logs` - All security events
- `user_security` - User warning/block tracking
- `security_events` - Block/warn events with expiration

---

## Security Checklist for New Commands

Before deploying a new command, ensure:

- [ ] Rate limiting applied if command is resource-intensive
- [ ] Input validation for all user-provided data
- [ ] RBAC check if command should be restricted
- [ ] Audit logging for security-relevant actions
- [ ] Error handling that doesn't expose internal details
- [ ] Length limits on all text inputs
- [ ] Profanity/spam checking on user content

---

## Example: Secure Command

```python
import nextcord
from nextcord.ext import commands
from src.utils.security import (
    rate_limit, require_verified, audit_action,
    sanitize, InputValidator, audit_log
)

class SecureCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @rate_limit('default')
    @require_verified()
    @audit_action('profile_updated')
    @commands.command()
    async def profile_update(self, ctx, field: str, *, value: str):
        """Update profile with security checks"""
        
        # Validate field name
        allowed_fields = {'title', 'skills', 'experience', 'looking_for'}
        if field not in allowed_fields:
            await ctx.send("❌ Invalid field name.")
            return
        
        # Sanitize input
        safe_value = sanitize(value, max_length=500)
        
        # Check for inappropriate content
        if not is_safe(safe_value):
            await ctx.send("❌ Content contains inappropriate language.")
            
            # Log security event
            await audit_log.record(
                user_id=str(ctx.author.id),
                action='inappropriate_content_blocked',
                details={'field': field, 'content_preview': safe_value[:50]},
                severity='warning'
            )
            return
        
        # Update profile
        await self.update_profile(ctx.author.id, field, safe_value)
        await ctx.send("✅ Profile updated successfully!")

def setup(bot):
    bot.add_cog(SecureCog(bot))
```

---

## Security Monitoring

### View recent security events:
```bash
# Get last 100 audit logs
SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 100;

# Get critical events
SELECT * FROM audit_logs WHERE severity = 'critical' ORDER BY created_at DESC;

# Get user's recent activity
SELECT * FROM audit_logs WHERE user_id = '123456789' ORDER BY created_at DESC;
```

### Monitor for suspicious patterns:
```python
# Check user for suspicious activity
is_suspicious = await audit_log.detect_suspicious_activity(user_id)

# Get user's action counts
actions = await audit_log.get_user_actions(user_id, hours=24)
```

---

## Emergency Procedures

### Block a user immediately:
```python
await db.execute(
    """INSERT INTO user_security (user_id, is_blocked, blocked_reason, blocked_until)
       VALUES ($1, TRUE, $2, NOW() + INTERVAL '24 hours')
       ON CONFLICT (user_id) 
       DO UPDATE SET is_blocked = TRUE, blocked_reason = $2, blocked_until = NOW() + INTERVAL '24 hours'""",
    user_id, "Spam detected"
)
```

### View blocked users:
```sql
SELECT * FROM user_security WHERE is_blocked = TRUE;
```

---

**Your bot now has enterprise-grade security!** 🛡️
