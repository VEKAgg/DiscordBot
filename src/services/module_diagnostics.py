"""Permission diagnostics using the bot snapshot; unknown channel permissions are explicit."""

import json

from src.services.module_registry import MODULES, PERMISSION_BITS

CHANNEL_MODULES = {
    'welcome_channel_id': 'welcome',
    'leaderboard_channel_id': 'leaderboards',
    'marketplace_channel_id': 'marketplace',
    'log_channel_id': 'moderation',
    'public_commands_channel_id': 'notifications',
}


def diagnostics(snapshot: dict, settings: dict, disabled: set[str]) -> list[dict]:
    result = []
    raw = snapshot.get('channels') or []
    channels = json.loads(raw) if isinstance(raw, str) else raw
    by_id = {str(c['id']): c for c in channels}
    permissions = snapshot.get('bot_permissions')
    for module in MODULES:
        if module.id in disabled or any(dep in disabled for dep in module.requires):
            continue
        bits = int(permissions) if permissions is not None else None
        missing = (
            ['PERMISSIONS_UNKNOWN']
            if bits is None
            else [p for p in module.permissions if not (bits & 8 or bits & PERMISSION_BITS[p])]
        )
        if missing:
            result.append({'module': module.id, 'setting_key': None, 'channel_id': None, 'missing': missing})
    for column, module_id in CHANNEL_MODULES.items():
        if module_id in disabled or not settings.get(column):
            continue
        channel_id = str(settings[column])
        channel = by_id.get(channel_id)
        bits = channel.get('bot_permissions') if channel else None
        if channel is None:
            missing = ['CHANNEL_MISSING']
        elif bits is None:
            missing = ['PERMISSIONS_UNKNOWN']
        else:
            value = int(bits)
            missing = [
                p
                for p in ('VIEW_CHANNEL', 'SEND_MESSAGES', 'EMBED_LINKS')
                if not (value & 8 or value & PERMISSION_BITS[p])
            ]
        if missing:
            result.append({'module': module_id, 'setting_key': column, 'channel_id': channel_id, 'missing': missing})
    return result
