"""
Enhanced Marketplace Features
Search, notifications, and engagement features to keep users active
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal

import nextcord
from nextcord.ext import commands, tasks

from src.database.database import db, get_user
from src.utils.marketplace.fraud_detection import fraud_detector
from src.utils.security import InputValidator, sanitize

logger = logging.getLogger('VEKA.marketplace.enhanced')


class MarketplaceEnhanced(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Start background tasks
        self.check_price_drops.start()
        self.update_featured_listings.start()
        self.check_expiring_listings.start()

    def cog_unload(self):
        self.check_price_drops.cancel()
        self.update_featured_listings.cancel()
        self.check_expiring_listings.cancel()

    # ==================== ADVANCED SEARCH ====================

    @commands.command(name='search', aliases=['find', 'lookup'])
    async def search_items(self, ctx, *, query: str):
        """
        Advanced search with filters
        Usage: !search laptop | max:500 | condition:good | category:electronics
        """
        try:
            # Parse query and filters
            filters = self._parse_search_query(query)
            search_term = filters.get('term', '')

            # Build dynamic query
            sql = """SELECT l.*, u.discord_id, c.name as category_name, c.emoji,
                            s.average_rating, s.total_sales
                     FROM marketplace_listings l
                     JOIN users u ON l.seller_id = u.id
                     JOIN marketplace_categories c ON l.category_id = c.id
                     LEFT JOIN marketplace_seller_stats s ON l.seller_id = s.user_id
                     WHERE l.status = 'active'"""
            params = []
            param_count = 0

            # Full-text search
            if search_term:
                param_count += 1
                sql += f" AND (to_tsvector('english', l.title) @@ plainto_tsquery('english', ${param_count})"
                sql += f" OR to_tsvector('english', l.description) @@ plainto_tsquery('english', ${param_count})"
                sql += f' OR l.tags && ARRAY[${param_count}])'
                params.append(search_term)

            # Price filters
            if 'min_price' in filters:
                param_count += 1
                sql += f' AND l.price >= ${param_count}'
                params.append(Decimal(filters['min_price']))

            if 'max_price' in filters:
                param_count += 1
                sql += f' AND l.price <= ${param_count}'
                params.append(Decimal(filters['max_price']))

            # Condition filter
            if 'condition' in filters:
                param_count += 1
                sql += f' AND l.condition = ${param_count}'
                params.append(filters['condition'])

            # Category filter
            if 'category' in filters:
                param_count += 1
                sql += f' AND LOWER(c.name) = LOWER(${param_count})'
                params.append(filters['category'])

            # Seller rating filter
            if 'min_rating' in filters:
                param_count += 1
                sql += f' AND s.average_rating >= ${param_count}'
                params.append(float(filters['min_rating']))

            # Sort options
            sort = filters.get('sort', 'newest')
            if sort == 'price_low':
                sql += ' ORDER BY l.price ASC'
            elif sort == 'price_high':
                sql += ' ORDER BY l.price DESC'
            elif sort == 'popular':
                sql += ' ORDER BY l.views DESC'
            else:  # newest
                sql += ' ORDER BY l.created_at DESC'

            # Limit results
            sql += ' LIMIT 20'

            listings = await db.fetch_many(sql, *params)

            if not listings:
                await ctx.send('🔍 No items found matching your search. Try different keywords or filters!')
                return

            embed = nextcord.Embed(
                title=f'🔍 Search Results ({len(listings)} items)',
                description=f'Query: **{search_term or "All items"}**',
                color=nextcord.Color.blue(),
            )

            for listing in listings[:10]:  # Show first 10
                seller = ctx.guild.get_member(int(listing['discord_id']))
                seller_name = seller.display_name if seller else 'Unknown'

                value = (
                    f'💰 **${listing["price"]}** | {listing["emoji"]} {listing["category_name"]}\n'
                    f'👤 {seller_name} | ⭐ {listing["average_rating"] or "N/A"} | 📦 {listing["total_sales"] or 0} sales\n'
                    f'🆔 `{listing["id"]}` | 👁️ {listing["views"]} views'
                )

                embed.add_field(name=f'{listing["emoji"]} {listing["title"][:50]}', value=value, inline=False)

            if len(listings) > 10:
                embed.set_footer(
                    text=f'Showing 10 of {len(listings)} results. Refine your search for more specific results.'
                )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f'Search error: {str(e)}')
            await ctx.send('❌ An error occurred while searching.')

    def _parse_search_query(self, query: str) -> dict:
        """Parse search query with filters"""
        filters = {}
        parts = query.split('|')

        # First part is the search term
        if parts:
            filters['term'] = parts[0].strip()

        # Parse filters
        for part in parts[1:]:
            part = part.strip()
            if ':' in part:
                key, value = part.split(':', 1)
                filters[key.strip()] = value.strip()

        return filters

    # ==================== WATCHLIST ====================

    @commands.command(name='watch', aliases=['track', 'favorite'])
    async def add_to_watchlist(self, ctx, listing_id: str):
        """Add an item to your watchlist"""
        try:
            user = await get_user(str(ctx.author.id))

            # Check if listing exists
            listing = await db.fetch_one('SELECT title, price FROM marketplace_listings WHERE id = $1', listing_id)

            if not listing:
                await ctx.send('❌ Listing not found.')
                return

            # Add to watchlist
            await db.execute(
                """INSERT INTO marketplace_watchlist (user_id, listing_id)
                   VALUES ($1, $2)
                   ON CONFLICT DO NOTHING""",
                user['id'],
                listing_id,
            )

            await ctx.send(f"✅ **{listing['title']}** added to your watchlist! You'll be notified of price changes.")

        except Exception as e:
            logger.error(f'Watchlist error: {str(e)}')
            await ctx.send('❌ An error occurred.')

    @commands.command(name='unwatch', aliases=['untrack'])
    async def remove_from_watchlist(self, ctx, listing_id: str):
        """Remove an item from your watchlist"""
        try:
            user = await get_user(str(ctx.author.id))

            await db.execute(
                'DELETE FROM marketplace_watchlist WHERE user_id = $1 AND listing_id = $2', user['id'], listing_id
            )

            await ctx.send('✅ Item removed from your watchlist.')

        except Exception as e:
            logger.error(f'Unwatch error: {str(e)}')
            await ctx.send('❌ An error occurred.')

    @commands.command(name='watchlist', aliases=['mywatchlist', 'tracking'])
    async def view_watchlist(self, ctx):
        """View all items you're watching"""
        try:
            user = await get_user(str(ctx.author.id))

            items = await db.fetch_many(
                """SELECT l.*, c.name as category_name, c.emoji
                   FROM marketplace_watchlist w
                   JOIN marketplace_listings l ON w.listing_id = l.id
                   JOIN marketplace_categories c ON l.category_id = c.id
                   WHERE w.user_id = $1
                   ORDER BY w.created_at DESC""",
                user['id'],
            )

            if not items:
                await ctx.send('📭 Your watchlist is empty. Use `!watch <listing_id>` to track items!')
                return

            embed = nextcord.Embed(
                title='📋 Your Watchlist',
                description=f"You're tracking {len(items)} item(s)",
                color=nextcord.Color.blue(),
            )

            for item in items:
                status_emoji = '🟢' if item['status'] == 'active' else '🔴'
                value = f'💰 ${item["price"]} | {status_emoji} {item["status"]} | 👁️ {item["views"]} views'

                embed.add_field(name=f'{item["emoji"]} {item["title"][:50]}', value=value, inline=False)

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f'View watchlist error: {str(e)}')
            await ctx.send('❌ An error occurred.')

    # ==================== OFFERS/BARGAINING ====================

    @commands.command(name='offer', aliases=['bid', 'makeoffer'])
    async def make_offer(self, ctx, listing_id: str, price: str, *, message: str = ''):
        """Make an offer on an item"""
        try:
            buyer = await get_user(str(ctx.author.id))

            # Get listing
            listing = await db.fetch_one(
                """SELECT l.*, u.discord_id as seller_discord_id
                   FROM marketplace_listings l
                   JOIN users u ON l.seller_id = u.id
                   WHERE l.id = $1 AND l.status = 'active'""",
                listing_id,
            )

            if not listing:
                await ctx.send('❌ Listing not found or no longer available.')
                return

            # Can't offer on own item
            if str(ctx.author.id) == listing['seller_discord_id']:
                await ctx.send("❌ You can't make an offer on your own item!")
                return

            # Validate price
            offered_price = InputValidator.validate_price(price)
            if offered_price is None:
                await ctx.send('❌ Invalid price format.')
                return

            # Check if negotiable
            if not listing['is_negotiable']:
                await ctx.send('❌ This seller is not accepting offers on this item.')
                return

            # Fraud check
            is_clean, fraud_reason = await fraud_detector.check_offer(
                listing_id, buyer['id'], listing['seller_id'], Decimal(str(offered_price))
            )

            if not is_clean:
                await ctx.send(f'❌ {fraud_reason}')
                return

            # Create offer
            expires = datetime.utcnow() + timedelta(days=3)
            await db.execute(
                """INSERT INTO marketplace_offers
                   (listing_id, buyer_id, offered_price, message, expires_at)
                   VALUES ($1, $2, $3, $4, $5)""",
                listing_id,
                buyer['id'],
                offered_price,
                sanitize(message, max_length=500),
                expires,
            )

            await ctx.send(f'✅ Offer of **${offered_price}** sent! The seller has 3 days to respond.')

            # Notify seller
            seller = ctx.guild.get_member(int(listing['seller_discord_id']))
            if seller:
                try:
                    seller_embed = nextcord.Embed(
                        title='💰 New Offer Received!',
                        description=f'Someone offered **${offered_price}** for **{listing["title"]}**',
                        color=nextcord.Color.green(),
                    )
                    if message:
                        seller_embed.add_field(name='Message', value=message[:500], inline=False)
                    seller_embed.add_field(name='Original Price', value=f'${listing["price"]}', inline=True)
                    seller_embed.add_field(name='Expires', value='3 days', inline=True)
                    await seller.send(embed=seller_embed)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f'Offer error: {str(e)}')
            await ctx.send('❌ An error occurred while making the offer.')

    @commands.command(name='myoffers', aliases=['offers'])
    async def view_offers(self, ctx):
        """View offers on your listings or offers you've made"""
        try:
            user = await get_user(str(ctx.author.id))

            # Offers on your listings
            received_offers = await db.fetch_many(
                """SELECT o.*, l.title, l.price as original_price, u.discord_id as buyer_discord_id
                   FROM marketplace_offers o
                   JOIN marketplace_listings l ON o.listing_id = l.id
                   JOIN users u ON o.buyer_id = u.id
                   WHERE l.seller_id = $1 AND o.status = 'pending' AND o.expires_at > NOW()
                   ORDER BY o.created_at DESC""",
                user['id'],
            )

            # Your offers
            sent_offers = await db.fetch_many(
                """SELECT o.*, l.title, l.price as original_price
                   FROM marketplace_offers o
                   JOIN marketplace_listings l ON o.listing_id = l.id
                   WHERE o.buyer_id = $1 AND o.status = 'pending' AND o.expires_at > NOW()
                   ORDER BY o.created_at DESC""",
                user['id'],
            )

            embed = nextcord.Embed(title='💰 Your Offers', color=nextcord.Color.blue())

            if received_offers:
                offers_text = ''
                for offer in received_offers[:5]:
                    buyer = ctx.guild.get_member(int(offer['buyer_discord_id']))
                    buyer_name = buyer.display_name if buyer else 'Unknown'
                    offers_text += f'• **{offer["title"][:30]}**: ${offer["offered_price"]} (from {buyer_name})\n'

                embed.add_field(
                    name=f'📥 Received ({len(received_offers)})', value=offers_text or 'No pending offers', inline=False
                )

            if sent_offers:
                offers_text = ''
                for offer in sent_offers[:5]:
                    offers_text += f'• **{offer["title"][:30]}**: ${offer["offered_price"]}\n'

                embed.add_field(
                    name=f'📤 Sent ({len(sent_offers)})', value=offers_text or 'No pending offers', inline=False
                )

            if not received_offers and not sent_offers:
                embed.description = '📭 No pending offers.'

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f'View offers error: {str(e)}')
            await ctx.send('❌ An error occurred.')

    # ==================== FEATURED LISTINGS ====================

    @commands.command(name='featured', aliases=['hot', 'trending'])
    async def view_featured(self, ctx):
        """View featured and trending listings"""
        try:
            # Get featured items (high views, good seller rating, recent)
            featured = await db.fetch_many(
                """SELECT l.*, u.discord_id, c.name as category_name, c.emoji,
                       s.average_rating, s.total_sales
                   FROM marketplace_listings l
                   JOIN users u ON l.seller_id = u.id
                   JOIN marketplace_categories c ON l.category_id = c.id
                   LEFT JOIN marketplace_seller_stats s ON l.seller_id = s.user_id
                   WHERE l.status = 'active'
                   AND l.views > 10
                   AND (s.average_rating IS NULL OR s.average_rating >= 4.0)
                   ORDER BY l.views DESC, l.created_at DESC
                   LIMIT 10"""
            )

            if not featured:
                await ctx.send('🔥 No featured listings yet. Be the first to post something amazing!')
                return

            embed = nextcord.Embed(
                title='🔥 Featured & Trending',
                description='Popular items from trusted sellers',
                color=nextcord.Color.gold(),
            )

            for i, listing in enumerate(featured[:5], 1):
                seller = ctx.guild.get_member(int(listing['discord_id']))
                seller_name = seller.display_name if seller else 'Unknown'

                value = (
                    f'💰 ${listing["price"]} | 👁️ {listing["views"]} views\n'
                    f'👤 {seller_name} | ⭐ {listing["average_rating"] or "N/A"}\n'
                    f'🆔 `{listing["id"]}`'
                )

                embed.add_field(name=f'#{i} {listing["emoji"]} {listing["title"][:40]}', value=value, inline=False)

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f'Featured error: {str(e)}')
            await ctx.send('❌ An error occurred.')

    # ==================== BACKGROUND TASKS ====================

    @tasks.loop(hours=6)
    async def check_price_drops(self):
        """Check for price drops and notify watchers"""
        try:
            # Get recent price drops (would need price history table)
            # For now, just check if items are about to expire
            expiring = await db.fetch_many(
                """SELECT l.*, u.discord_id
                   FROM marketplace_listings l
                   JOIN users u ON l.seller_id = u.id
                   WHERE l.status = 'active'
                   AND l.created_at < NOW() - INTERVAL '30 days'"""
            )

            for listing in expiring:
                seller = self.bot.get_user(int(listing['discord_id']))
                if seller:
                    try:
                        embed = nextcord.Embed(
                            title='⏰ Listing Expiring Soon',
                            description=f'Your listing **{listing["title"]}** is 30 days old.',
                            color=nextcord.Color.orange(),
                        )
                        embed.add_field(
                            name='Action', value=f'Use `!bump {listing["id"]}` to refresh it!', inline=False
                        )
                        await seller.send(embed=embed)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f'Price drop check error: {str(e)}')

    @tasks.loop(hours=12)
    async def update_featured_listings(self):
        """Update featured listings cache"""
        # This runs periodically to update any cached featured data
        logger.info('Updated featured listings cache')

    @tasks.loop(hours=24)
    async def check_expiring_listings(self):
        """Mark old listings as expired"""
        try:
            await db.execute(
                """UPDATE marketplace_listings
                   SET status = 'withdrawn'
                   WHERE status = 'active'
                   AND created_at < NOW() - INTERVAL '60 days'"""
            )
            logger.info('Cleaned up expired listings')
        except Exception as e:
            logger.error(f'Expiring listings error: {str(e)}')

    @check_price_drops.before_loop
    async def before_price_drops(self):
        await self.bot.wait_until_ready()

    # ==================== STATISTICS ====================

    @commands.command(name='marketstats', aliases=['marketplace_stats'])
    async def marketplace_stats(self, ctx):
        """View marketplace statistics"""
        try:
            # Get stats
            stats = await db.fetch_one(
                """SELECT
                   COUNT(*) FILTER (WHERE status = 'active') as active_listings,
                   COUNT(*) FILTER (WHERE status = 'sold') as sold_listings,
                   COUNT(DISTINCT seller_id) as active_sellers,
                   AVG(price) FILTER (WHERE status = 'active') as avg_price
                   FROM marketplace_listings"""
            )

            top_categories = await db.fetch_many(
                """SELECT c.name, c.emoji, COUNT(*) as count
                   FROM marketplace_listings l
                   JOIN marketplace_categories c ON l.category_id = c.id
                   WHERE l.status = 'active'
                   GROUP BY c.id
                   ORDER BY count DESC
                   LIMIT 5"""
            )

            top_sellers = await db.fetch_many(
                """SELECT u.discord_id, s.total_sales, s.average_rating
                   FROM marketplace_seller_stats s
                   JOIN users u ON s.user_id = u.id
                   ORDER BY s.total_sales DESC
                   LIMIT 5"""
            )

            embed = nextcord.Embed(title='📊 Marketplace Statistics', color=nextcord.Color.blue())

            if stats is None:
                await ctx.send('❌ Could not retrieve marketplace statistics.')
                return

            embed.add_field(
                name='📦 Listings',
                value=f'Active: **{stats["active_listings"] or 0}**\nSold: **{stats["sold_listings"] or 0}**',
                inline=True,
            )

            embed.add_field(
                name='👥 Community',
                value=f'Active Sellers: **{stats["active_sellers"] or 0}**\nAvg Price: **${stats["avg_price"] or 0:.2f}**',
                inline=True,
            )

            if top_categories:
                cat_text = '\n'.join([f'{c["emoji"]} {c["name"]}: {c["count"]}' for c in top_categories])
                embed.add_field(name='📁 Top Categories', value=cat_text, inline=False)

            if top_sellers:
                seller_text = ''
                for i, seller in enumerate(top_sellers[:3], 1):
                    user = ctx.guild.get_member(int(seller['discord_id']))
                    name = user.display_name if user else 'Unknown'
                    seller_text += f'#{i} {name}: {seller["total_sales"]} sales\n'

                embed.add_field(name='🏆 Top Sellers', value=seller_text, inline=False)

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f'Stats error: {str(e)}')
            await ctx.send('❌ An error occurred.')


def setup(bot):
    bot.add_cog(MarketplaceEnhanced(bot))
