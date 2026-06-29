import functools
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import nextcord

logger = logging.getLogger('VEKA.embeds')

VEKA_AUTHOR_NAME = 'VEKA Bot'
VEKA_AUTHOR_URL = 'https://veka.gg'
REPO_URL = 'https://github.com/VEKAgg/DiscordBot'
DEFAULT_CONTRIBUTOR = {'name': 'shifu', 'discord_id': '941009204045557842'}
ORANGE = nextcord.Color.orange()

# Best-effort contributor attribution mapping for known modules.
# This is a static local fallback to avoid expensive runtime API calls.
_STATIC_CONTRIBUTOR_MAP: dict[str, dict[str, str]] = {
    'src.cogs.admin.basic': DEFAULT_CONTRIBUTOR,
    'src.cogs.admin.help': DEFAULT_CONTRIBUTOR,
    'src.cogs.admin.health': DEFAULT_CONTRIBUTOR,
    'src.cogs.admin.moderation': DEFAULT_CONTRIBUTOR,
    'src.cogs.admin.notifications': DEFAULT_CONTRIBUTOR,
    'src.cogs.networking.networking': DEFAULT_CONTRIBUTOR,
    'src.cogs.marketplace.marketplace': DEFAULT_CONTRIBUTOR,
    'src.cogs.marketplace.reviews': DEFAULT_CONTRIBUTOR,
    'src.cogs.marketplace_enhanced': DEFAULT_CONTRIBUTOR,
    'src.cogs.mentorship': DEFAULT_CONTRIBUTOR,
    'src.cogs.portfolio.portfolio_manager': DEFAULT_CONTRIBUTOR,
    'src.cogs.resources.feeds': DEFAULT_CONTRIBUTOR,
    'src.cogs.radio': DEFAULT_CONTRIBUTOR,
    'src.cogs.rpg': DEFAULT_CONTRIBUTOR,
    'src.cogs.external.info': DEFAULT_CONTRIBUTOR,
    'src.cogs.external.export': DEFAULT_CONTRIBUTOR,
}


def _git_author_for_path(path: Path) -> str | None:
    try:
        author = subprocess.check_output(
            ['git', 'log', '-1', '--format=%an', '--', str(path)],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return author if author else None
    except Exception as exc:
        logger.debug('Git author lookup failed for %s: %s', path, exc)
        return None


@functools.lru_cache(maxsize=64)
def get_contributor(source: str | None = None) -> dict[str, str]:
    if source:
        if source in _STATIC_CONTRIBUTOR_MAP:
            return _STATIC_CONTRIBUTOR_MAP[source]

        # Accept module path or file path
        normalized = source.replace('\\', '/').replace('.py', '')
        for key in _STATIC_CONTRIBUTOR_MAP:
            if key.endswith(normalized) or normalized.endswith(key):
                return _STATIC_CONTRIBUTOR_MAP[key]

        try:
            source_path = Path(source)
            if source_path.exists():
                author = _git_author_for_path(source_path)
                if author:
                    return {'name': author, 'discord_id': DEFAULT_CONTRIBUTOR['discord_id']}
        except Exception:
            pass

    return DEFAULT_CONTRIBUTOR


async def veka_embed(
    title: str | None = None,
    description: str | None = None,
    color: nextcord.Color = ORANGE,
    contributor_source: str | None = None,
    user: nextcord.Member | nextcord.User | None = None,
    guild: nextcord.Guild | None = None,
    timestamp: bool = True,
    footer: bool = True,
) -> nextcord.Embed:
    contributor = get_contributor(contributor_source)
    embed = nextcord.Embed(title=title or '', description=description or '', color=color)
    embed.set_author(name=VEKA_AUTHOR_NAME, url=VEKA_AUTHOR_URL)
    if footer:
        from src.utils.footer import build_footer

        footer_text = await build_footer(user, contributor, guild=guild)
        if footer_text:
            embed.set_footer(text=footer_text)
    if timestamp:
        embed.timestamp = datetime.utcnow()
    return embed


async def success_embed(
    title: str | None = None,
    description: str | None = None,
    **kwargs: Any,
) -> nextcord.Embed:
    return await veka_embed(title=title, description=description, **kwargs)


async def error_embed(
    title: str | None = 'Error',
    description: str | None = None,
    **kwargs: Any,
) -> nextcord.Embed:
    return await veka_embed(title=title, description=description, **kwargs)


async def info_embed(
    title: str | None = 'Info',
    description: str | None = None,
    **kwargs: Any,
) -> nextcord.Embed:
    return await veka_embed(title=title, description=description, **kwargs)


async def alert_embed(
    title: str,
    description: str,
    severity: str = 'INFO',
    **kwargs: Any,
) -> nextcord.Embed:
    colors = {
        'INFO': nextcord.Color.blue(),
        'WARN': nextcord.Color.gold(),
        'ERROR': nextcord.Color.red(),
        'CRITICAL': nextcord.Color.dark_red(),
    }
    color = colors.get(severity.upper(), ORANGE)
    return await veka_embed(title=f'[{severity.upper()}] {title}', description=description, color=color, **kwargs)
