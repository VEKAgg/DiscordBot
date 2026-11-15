"""Origin-scoped advanced search over the canonical marketplace projection."""

from __future__ import annotations

import nextcord
from nextcord.ext import commands

from src.database.database import db
from src.services.marketplace_ingestion import READ_SCOPE, available_channels
from src.services.marketplace_service import normalize_search_filters
from src.utils.safety import safe_send


class MarketplaceEnhanced(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _parse_search_query(self, query: str) -> dict:
        if not query.strip() or len(query) > 1000:
            raise ValueError('Enter a search query of at most 1000 characters.')
        segments = query.split('|')
        filters = {'term': segments[0].strip()}
        for part in segments[1:]:
            if ':' not in part:
                raise ValueError('Use filter:value after each | separator.')
            key, value = part.split(':', 1)
            key = key.strip()
            if key in filters:
                raise ValueError('Specify each search filter once.')
            filters[key] = value.strip()
        return normalize_search_filters(filters)

    async def _run_search(self, filters: dict, interaction=None) -> list[dict]:
        filters = normalize_search_filters(filters)
        if interaction is None or interaction.guild is None:
            return []  # No implicit global search context.
        sql = f"""SELECT l.*,u.discord_id,c.name AS category_name,c.emoji
                  FROM marketplace_listings l JOIN users u ON u.id=l.seller_id
                  LEFT JOIN marketplace_categories c ON c.id=l.category_id WHERE {READ_SCOPE}"""
        params = [interaction.guild.id, available_channels(interaction), None]
        for field, clause in (
            ('term', "to_tsvector('english',l.title||' '||l.description) @@ plainto_tsquery('english',${n})"),
            ('min_price', 'l.price>=${n}'),
            ('max_price', 'l.price<=${n}'),
            ('condition', 'l.condition=${n}'),
            ('category', 'c.core_id::text=${n}'),
        ):
            if field in filters and filters[field] != '':
                params.append(filters[field])
                sql += ' AND (' + clause.format(n=len(params)) + ')'
        if 'min_price' in filters or 'max_price' in filters:
            # Bot search defaults to USD; never compare unlike currencies.
            sql += " AND l.currency='USD'"
        if 'min_rating' in filters:
            raise ValueError('Verified transaction ratings are not part of classifieds.')
        sort = filters.get('sort', 'newest')
        order = {
            'price_low': 'l.price ASC NULLS LAST',
            'price_high': 'l.price DESC NULLS LAST',
            'popular': 'l.views DESC',
            'newest': 'l.created_at DESC',
        }[sort]
        return await db.fetch_many(sql + ' ORDER BY ' + order + ',l.id DESC LIMIT 20', *params)

    async def search_slash(self, interaction, query: str):
        try:
            rows = await self._run_search(self._parse_search_query(query), interaction)
            embed = nextcord.Embed(title='Marketplace search')
            for row in rows[:10]:
                embed.add_field(
                    name=row['title'][:100], value=f'`{row["id"]}` · {row["price"]} {row["currency"]}', inline=False
                )
            if not rows:
                embed.description = 'No readable listings match in this server.'
            await safe_send(interaction, embed=embed, ephemeral=True)
        except ValueError as exc:
            await safe_send(interaction, content=str(exc), ephemeral=True)


def setup(bot):
    bot.add_cog(MarketplaceEnhanced(bot))
