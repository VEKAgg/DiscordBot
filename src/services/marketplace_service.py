"""Shared marketplace price and atomic listing lifecycle operations."""

from decimal import Decimal, InvalidOperation

from src.database.database import Database, db
from src.utils.embed_limits import text_units

MAX_PRICE = Decimal('999999.99')


def validate_price(value: str | float | Decimal, *, allow_zero: bool = False) -> Decimal:
    raw = str(value).strip().removeprefix('$').strip()
    if len(raw) > 64:
        raise ValueError('Use a dollar amount of at most 64 characters.')
    try:
        price = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ValueError('Use a valid dollar amount with at most two decimal places.') from None
    if not price.is_finite() or not Decimal(0) <= price <= MAX_PRICE or (not allow_zero and price == 0):
        raise ValueError(
            'Price must be greater than $0 and at most $999,999.99.'
            if not allow_zero
            else 'Price filter must be between $0 and $999,999.99.'
        )
    if price != price.quantize(Decimal('0.01')):
        raise ValueError('Use at most two decimal places for the price.')
    return price.quantize(Decimal('0.01'))


def validate_listing_text(title: str, description: str) -> tuple[str, str]:
    title, description = title.strip(), description.strip()
    if not 3 <= text_units(title) <= 100:
        raise ValueError('Title must be between 3 and 100 characters.')
    if text_units(description) > 3000:
        raise ValueError('Description must be at most 3000 characters.')
    return title, description


def normalize_search_filters(filters: dict) -> dict:
    allowed = {'term', 'min_price', 'max_price', 'condition', 'category', 'min_rating', 'sort'}
    if filters.keys() - allowed:
        raise ValueError('Unknown marketplace search filter.')
    result: dict = {}
    for key, value in filters.items():
        value = str(value).strip()
        if not value and key != 'term':
            raise ValueError(f'Specify a value for {key}.')
        if text_units(value) > 200:
            raise ValueError('Search values must be at most 200 characters.')
        if key in {'min_price', 'max_price'}:
            result[key] = validate_price(value, allow_zero=True)
        elif key == 'min_rating':
            try:
                rating = Decimal(value)
            except InvalidOperation:
                raise ValueError('Minimum rating must be a number from 0 to 5.') from None
            if not rating.is_finite() or not Decimal(0) <= rating <= Decimal(5):
                raise ValueError('Minimum rating must be a number from 0 to 5.')
            normalized = rating.quantize(Decimal('0.01'))
            if normalized != rating:
                raise ValueError('Minimum rating may have at most two decimal places.')
            result[key] = normalized
        elif key == 'condition':
            if value not in {'new', 'like_new', 'good', 'fair', 'poor', 'unknown'}:
                raise ValueError('Unknown condition filter.')
            result[key] = value
        elif key == 'sort':
            if value not in {'newest', 'price_low', 'price_high', 'popular'}:
                raise ValueError('Sort must be newest, price_low, price_high or popular.')
            result[key] = value
        else:
            result[key] = value
    if result.get('min_price', Decimal(0)) > result.get('max_price', MAX_PRICE):
        raise ValueError('Minimum price must not exceed maximum price.')
    return result


async def bump_listing(listing_id: str, owner_id: int, *, database: Database = db) -> bool:
    """The owner/status/cooldown check and bump happen in one statement under PostgreSQL's row lock."""
    row = await database.fetch_one(
        """UPDATE marketplace_listings l SET last_bumped_at = NOW(), is_expired = FALSE
           FROM users u
           WHERE l.id = $1 AND l.seller_id = u.id AND u.discord_id = $2
             AND l.status = 'active'
             AND (l.last_bumped_at IS NULL OR l.last_bumped_at <= NOW() - INTERVAL '24 hours')
           RETURNING l.id""",
        listing_id,
        str(owner_id),
    )
    return row is not None
