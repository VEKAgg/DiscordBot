"""Shared bounded portfolio writes and page queries. Visibility remains global, as before."""

import secrets
from datetime import UTC, datetime

import validators

from src.database.database import db, get_or_create_user
from src.utils.embed_limits import text_units
from src.utils.safety import ValidationError

PAGE_SIZE = 5
MAX_PAGE = 1000


def validate_project(
    title: str, description: str, url: str = '', tags: str = ''
) -> tuple[str, str, str | None, list[str]]:
    title, description, url = title.strip(), description.strip(), url.strip()
    if not title or text_units(title) > 200:
        raise ValidationError('Project title must be 1–200 characters.')
    if not description or text_units(description) > 3000:
        raise ValidationError('Project description must be 1–3000 characters.')
    if url and (
        text_units(url) > 500 or not url.lower().startswith(('https://', 'http://')) or not validators.url(url)
    ):
        raise ValidationError('Project URL must be a valid HTTP(S) URL of at most 500 characters, or omitted.')
    tag_list: list[str] = []
    seen: set[str] = set()
    if text_units(tags) > 1000:
        raise ValidationError('Tags input must be at most 1000 characters.')
    for tag in tags.split(','):
        tag = tag.strip()
        if not tag:
            continue
        if text_units(tag) > 40:
            raise ValidationError('Each tag must be at most 40 characters.')
        if tag.casefold() not in seen:
            tag_list.append(tag)
            seen.add(tag.casefold())
    if len(tag_list) > 10:
        raise ValidationError('Use at most 10 unique tags.')
    return title, description, url or None, tag_list


def page_offset(page: int) -> int:
    if type(page) is not int or not 1 <= page <= MAX_PAGE:
        raise ValidationError(f'Page must be between 1 and {MAX_PAGE}.')
    return (page - 1) * PAGE_SIZE


def validate_project_id(project_id: str) -> str:
    project_id = project_id.strip()
    if not project_id or text_units(project_id) > 50:
        raise ValidationError('Project ID must be 1–50 characters.')
    return project_id


async def add_project(discord_id: int, title: str, description: str, url: str = '', tags: str = ''):
    title, description, url_value, tag_list = validate_project(title, description, url, tags)
    user = await get_or_create_user(str(discord_id))
    project_id = f'proj-{int(datetime.now(UTC).timestamp())}-{secrets.token_hex(8)}'
    await db.execute(
        'INSERT INTO portfolios (id, user_id, title, description, url, tags) VALUES ($1, $2, $3, $4, $5, $6)',
        project_id,
        user['id'],
        title,
        description,
        url_value,
        tag_list,
    )
    return {'id': project_id, 'title': title, 'url': url_value, 'tags': tag_list}


async def list_projects(discord_id: int, page: int = 1):
    offset = page_offset(page)
    # Reads do not create an otherwise absent target user.
    return await db.fetch_many(
        """SELECT p.* FROM portfolios p JOIN users u ON u.id = p.user_id
           WHERE u.discord_id = $1 ORDER BY p.created_at DESC, p.id DESC LIMIT $2 OFFSET $3""",
        str(discord_id),
        PAGE_SIZE + 1,
        offset,
    )


async def search_projects(query: str, page: int = 1):
    offset = page_offset(page)
    query = query.strip()
    if not query or text_units(query) > 200:
        raise ValidationError('Search query must be 1–200 characters.')
    return await db.fetch_many(
        """SELECT p.*, u.discord_id AS owner_discord_id
           FROM portfolios p JOIN users u ON u.id = p.user_id
           WHERE to_tsvector('english', p.title || ' ' || COALESCE(p.description, '')) @@ plainto_tsquery('english', $1)
              OR $1 = ANY(p.tags)
           ORDER BY p.created_at DESC, p.id DESC LIMIT $2 OFFSET $3""",
        query,
        PAGE_SIZE + 1,
        offset,
    )


async def get_project(project_id: str):
    return await db.fetch_one(
        """SELECT p.*, u.discord_id AS owner_discord_id FROM portfolios p
           JOIN users u ON u.id = p.user_id WHERE p.id = $1""",
        validate_project_id(project_id),
    )


async def delete_project(discord_id: int, project_id: str) -> bool:
    result = await db.execute(
        """DELETE FROM portfolios WHERE id = $1 AND user_id =
           (SELECT id FROM users WHERE discord_id = $2)""",
        validate_project_id(project_id),
        str(discord_id),
    )
    return result == 'DELETE 1'
