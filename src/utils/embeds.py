import functools
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import nextcord

logger = logging.getLogger('VEKA.embeds')

VEKA_AUTHOR_NAME = 'VEKA Bot'
VEKA_AUTHOR_URL = 'https://veka.gg'
REPO_URL = 'https://github.com/VEKAgg/DiscordBot'
DEFAULT_CONTRIBUTOR = {'name': 'shifu', 'discord_id': '941009204045557842'}
ORANGE = nextcord.Color.orange()

# Best-effort contributor attribution mapping for known modules.
# This is a static local fallback to avoid expensive runtime API calls.
_STATIC_CONTRIBUTOR_MAP: Dict[str, Dict[str, str]] = {
    'src.cogs.admin.basic': DEFAULT_CONTRIBUTOR,
    'src.cogs.admin.help': DEFAULT_CONTRIBUTOR,
    'src.cogs.admin.health': DEFAULT_CONTRIBUTOR,
    'src.cogs.networking.networking': DEFAULT_CONTRIBUTOR,
    'src.cogs.marketplace.marketplace': DEFAULT_CONTRIBUTOR,
    'src.cogs.marketplace.reviews': DEFAULT_CONTRIBUTOR,
    'src.cogs.resources.feeds': DEFAULT_CONTRIBUTOR,
}


def _git_author_for_path(path: Path) -> Optional[str]:
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
def get_contributor(source: Optional[str] = None) -> Dict[str, str]:
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


def _build_footer(contributor: Dict[str, str]) -> str:
    name = contributor.get('name', DEFAULT_CONTRIBUTOR['name'])
    return f'Command made by {name}, you can also contribute: {REPO_URL}'


def veka_embed(
    title: Optional[str] = None,
    description: Optional[str] = None,
    color: nextcord.Color = ORANGE,
    contributor_source: Optional[str] = None,
    timestamp: bool = True,
    footer: bool = True,
    include_repo_link: bool = False,
) -> nextcord.Embed:
    contributor = get_contributor(contributor_source)
    embed = nextcord.Embed(title=title or '', description=description or '', color=color)
    embed.set_author(name=VEKA_AUTHOR_NAME, url=VEKA_AUTHOR_URL)
    if footer:
        embed.set_footer(text=_build_footer(contributor))
    if timestamp:
        embed.timestamp = datetime.utcnow()
    if include_repo_link:
        embed.add_field(name='Contribute', value=REPO_URL, inline=False)
    return embed


def success_embed(
    title: Optional[str] = None,
    description: Optional[str] = None,
    **kwargs: Any,
) -> nextcord.Embed:
    return veka_embed(title=title, description=description, **kwargs)


def error_embed(
    title: Optional[str] = 'Error',
    description: Optional[str] = None,
    **kwargs: Any,
) -> nextcord.Embed:
    return veka_embed(title=title, description=description, **kwargs)


def info_embed(
    title: Optional[str] = 'Info',
    description: Optional[str] = None,
    **kwargs: Any,
) -> nextcord.Embed:
    return veka_embed(title=title, description=description, **kwargs)


def alert_embed(
    title: str,
    description: str,
    severity: str = "INFO",
    **kwargs: Any,
) -> nextcord.Embed:
    colors = {
        "INFO": nextcord.Color.blue(),
        "WARN": nextcord.Color.gold(),
        "ERROR": nextcord.Color.red(),
        "CRITICAL": nextcord.Color.dark_red()
    }
    color = colors.get(severity.upper(), ORANGE)
    return veka_embed(title=f"[{severity.upper()}] {title}", description=description, color=color, **kwargs)
