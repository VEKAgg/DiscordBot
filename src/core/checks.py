import logging
import urllib.parse

from src.config.config import ADMIN_ALERT_CHANNEL_ID, DATABASE_URL, DISCORD_TOKEN
from src.core.runtime_state import runtime_state
from src.database.database import db

logger = logging.getLogger('VEKA.checks')


class StartupChecks:
    @staticmethod
    async def run_all_checks() -> None:
        checks = [
            StartupChecks.check_config,
            StartupChecks.check_discord_token,
            StartupChecks.check_database_url,
            StartupChecks.check_database_connection,
            StartupChecks.check_admin_channel,
        ]

        results = []
        for check in checks:
            try:
                result = await check()
                results.append(result)
                logger.info('Startup check %s: %s', result['name'], result['status'])
            except Exception as e:
                logger.error('Startup check failed unexpectedly: %s', e)
                results.append({'name': check.__name__, 'status': 'FAIL', 'message': f'Check crashed: {e}'})

        runtime_state.startup_check_results = results

    @staticmethod
    async def check_config() -> dict:
        return {'name': 'Config Load', 'status': 'PASS', 'message': 'Environment variables loaded'}

    @staticmethod
    async def check_discord_token() -> dict:
        if not DISCORD_TOKEN or DISCORD_TOKEN == 'your_discord_bot_token_here':
            return {'name': 'Discord Token', 'status': 'FAIL', 'message': 'Invalid or missing DISCORD_TOKEN'}
        return {'name': 'Discord Token', 'status': 'PASS', 'message': 'Token present'}

    @staticmethod
    async def check_database_url() -> dict:
        if not DATABASE_URL:
            return {'name': 'Database URL', 'status': 'FAIL', 'message': 'DATABASE_URL is not configured'}
        try:
            parsed = urllib.parse.urlparse(DATABASE_URL)
            if parsed.scheme not in ('postgres', 'postgresql'):
                return {'name': 'Database URL', 'status': 'WARN', 'message': f'Suspicious DB scheme: {parsed.scheme}'}
            return {'name': 'Database URL', 'status': 'PASS', 'message': 'DATABASE_URL parsed successfully'}
        except Exception as e:
            return {'name': 'Database URL', 'status': 'FAIL', 'message': f'Failed to parse URL: {e}'}

    @staticmethod
    async def check_database_connection() -> dict:
        try:
            # Note: connect() should have been called before this check framework runs during boot
            await db.ping()
            return {'name': 'Database Connection', 'status': 'PASS', 'message': 'Successfully pinged PostgreSQL'}
        except Exception as e:
            return {'name': 'Database Connection', 'status': 'FAIL', 'message': f'Connection failed: {e}'}

    @staticmethod
    async def check_admin_channel() -> dict:
        if not ADMIN_ALERT_CHANNEL_ID:
            return {
                'name': 'Admin Channel',
                'status': 'WARN',
                'message': 'ADMIN_ALERT_CHANNEL_ID is not set. Operational alerts will not be delivered.',
            }
        return {'name': 'Admin Channel', 'status': 'PASS', 'message': 'Admin channel ID configured'}
