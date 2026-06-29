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
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.marketplace.fraud_detection import fraud_detector
from src.utils.safety import safe_send, safe_slash_command
from src.utils.security import InputValidator, sanitize

logger = logging.getLogger('VEKA.marketplace.enhanced')


class MarketplaceEnhanced(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_price_drops.start()
        self.update_featured_listings.start()
        self.check_expiring_listings.start()

    def cog_unload(self):
        self.check_price_drops.cancel()
        self.update_featured_listings.cancel()
        self.check_expiring_listings.cancel()

    # ==================== SLASH COMMANDS ====================

    @nextcord.slash_command(name='search', description='Advanced marketplace search with filters')
    @safe_slash_command(requires_db=True)
    async def search_slash(self, interaction: nextcord.Interaction, query: str):
        try:
            filters = self._parse_search_query(query)
            search_term = filters.get('term', '')
            listings = await self._run_search(filters)

            if not listings:
                embed = info_embed(
                    title='No Results', description='No items found matching your search.', contributor_source=__name__
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            embed = info_embed(
                title=f'🔍 Search Results ({len(listings)} items)',
                description=f'Query: **{search_term or "All items"}**',
                contributor_source=__name__,
            )

            for listing in listings[:10]:
                seller = interaction.guild.get_member(int(listing['discord_id']))
                seller_name = seller.display_name if seller else 'Unknown'

                value = (
                    f'💰 **${listing["price"]}** | {listing["emoji"]} {listing["category_name"]}\n'
                    f'👤 {seller_name} | ⭐ {listing["average_rating"] or "N/A"} | 📦 {listing["total_sales"] or 0} sales\n'
                    f'🆔 `{listing["id"]}` | 👁️ {listing["views"]} views'
                )
                embed.add_field(name=f'{listing["emoji"]} {listing["title"][:50]}', value=value, inline=False)

            if len(listings) > 10:
                embed.set_footer(text=f'Showing 10 of {len(listings)} results.')

            await safe_send(interaction, embed=embed, ephemeral=False)

        except Exception as e:
            logger.error(f'Search error: {str(e)}')
            embed = error_embed('Search Error', 'An error occurred while searching.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='watch', description='Add a listing to your watchlist')
    @safe_slash_command(requires_db=True)
    async def watch_slash(self, interaction: nextcord.Interaction, listing_id: str):
        try:
            user = await get_user(str(interaction.user.id))
            listing = await db.fetch_one('SELECT title, price FROM marketplace_listings WHERE id = $1', listing_id)

            if not listing:
                embed = error_embed('Not Found', 'Listing not found.', contributor_source=__name__)
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            await db.execute(
                'INSERT INTO marketplace_watchlist (user_id, listing_id) VALUES ($1, $2) ON CONFLICT DO NOTHING',
                user['id'],
                listing_id,
            )

            embed = success_embed(
                title='Added to Watchlist',
                description=f"**{listing['title']}** added to your watchlist! You'll be notified of price changes.",
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'Watchlist error: {str(e)}')
            embed = error_embed('Watchlist Error', 'An error occurred.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='unwatch', description='Remove a listing from your watchlist')
    @safe_slash_command(requires_db=True)
    async def unwatch_slash(self, interaction: nextcord.Interaction, listing_id: str):
        try:
            user = await get_user(str(interaction.user.id))
            await db.execute(
                'DELETE FROM marketplace_watchlist WHERE user_id = $1 AND listing_id = $2', user['id'], listing_id
            )

            embed = success_embed(
                title='Removed', description='Item removed from your watchlist.', contributor_source=__name__
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'Unwatch error: {str(e)}')
            embed = error_embed('Unwatch Error', 'An error occurred.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='watchlist', description='View all items you are watching')
    @safe_slash_command(requires_db=True)
    async def watchlist_slash(self, interaction: nextcord.Interaction):
        try:
            user = await get_user(str(interaction.user.id))

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
                embed = info_embed(
                    title='Your Watchlist',
                    description="You're not watching any items. Use `/watch` to track items!",
                    contributor_source=__name__,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            embed = info_embed(
                title='📋 Your Watchlist',
                description=f"You're tracking {len(items)} item(s)",
                contributor_source=__name__,
            )

            for item in items:
                status_emoji = '🟢' if item['status'] == 'active' else '🔴'
                value = f'💰 ${item["price"]} | {status_emoji} {item["status"]} | 👁️ {item["views"]} views'
                embed.add_field(name=f'{item["emoji"]} {item["title"][:50]}', value=value, inline=False)

            await safe_send(interaction, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'View watchlist error: {str(e)}')
            embed = error_embed('Watchlist Error', 'An error occurred.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='offer', description='Make an offer on a listing')
    @safe_slash_command(requires_db=True)
    async def offer_slash(self, interaction: nextcord.Interaction, listing_id: str, price: str, message: str = ''):
        try:
            buyer = await get_user(str(interaction.user.id))

            listing = await db.fetch_one(
                """SELECT l.*, u.discord_id as seller_discord_id
                   FROM marketplace_listings l
                   JOIN users u ON l.seller_id = u.id
                   WHERE l.id = $1 AND l.status = 'active'""",
                listing_id,
            )

            if not listing:
                embed = error_embed(
                    'Not Found', 'Listing not found or no longer available.', contributor_source=__name__
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            if str(interaction.user.id) == listing['seller_discord_id']:
                embed = error_embed(
                    'Invalid Action', "You can't make an offer on your own item!", contributor_source=__name__
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            offered_price = InputValidator.validate_price(price)
            if offered_price is None:
                embed = error_embed('Invalid Price', 'Invalid price format.', contributor_source=__name__)
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            if not listing['is_negotiable']:
                embed = error_embed(
                    'Not Negotiable', 'This seller is not accepting offers on this item.', contributor_source=__name__
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            is_clean, fraud_reason = await fraud_detector.check_offer(
                listing_id, buyer['id'], listing['seller_id'], Decimal(str(offered_price))
            )

            if not is_clean:
                embed = error_embed('Offer Blocked', fraud_reason, contributor_source=__name__)
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

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

            embed = success_embed(
                title='Offer Sent',
                description=f'Your offer of **${offered_price}** has been sent! The seller has 3 days to respond.',
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

            seller = interaction.guild.get_member(int(listing['seller_discord_id']))
            if seller:
                try:
                    seller_embed = info_embed(
                        title='💰 New Offer Received!',
                        description=f'Someone offered **${offered_price}** for **{listing["title"]}**',
                        contributor_source=__name__,
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
            embed = error_embed('Offer Error', 'An error occurred while making the offer.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='myoffers', description='View offers on your listings or offers you have made')
    @safe_slash_command(requires_db=True)
    async def myoffers_slash(self, interaction: nextcord.Interaction):
        try:
            user = await get_user(str(interaction.user.id))

            received_offers = await db.fetch_many(
                """SELECT o.*, l.title, l.price as original_price, u.discord_id as buyer_discord_id
                   FROM marketplace_offers o
                   JOIN marketplace_listings l ON o.listing_id = l.id
                   JOIN users u ON o.buyer_id = u.id
                   WHERE l.seller_id = $1 AND o.status = 'pending' AND o.expires_at > NOW()
                   ORDER BY o.created_at DESC""",
                user['id'],
            )

            sent_offers = await db.fetch_many(
                """SELECT o.*, l.title, l.price as original_price
                   FROM marketplace_offers o
                   JOIN marketplace_listings l ON o.listing_id = l.id
                   WHERE o.buyer_id = $1 AND o.status = 'pending' AND o.expires_at > NOW()
                   ORDER BY o.created_at DESC""",
                user['id'],
            )

            embed = info_embed(title='💰 Your Offers', contributor_source=__name__)

            if received_offers:
                offers_text = ''
                for offer in received_offers[:5]:
                    buyer = interaction.guild.get_member(int(offer['buyer_discord_id']))
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

            await safe_send(interaction, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'View offers error: {str(e)}')
            embed = error_embed('Offers Error', 'An error occurred.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='featured', description='View featured and trending listings')
    @safe_slash_command(requires_db=True)
    async def featured_slash(self, interaction: nextcord.Interaction):
        try:
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
                embed = info_embed(
                    title='No Featured Listings',
                    description='No featured listings yet. Be the first to post something amazing!',
                    contributor_source=__name__,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            embed = info_embed(
                title='🔥 Featured & Trending',
                description='Popular items from trusted sellers',
                contributor_source=__name__,
            )

            for i, listing in enumerate(featured[:5], 1):
                seller = interaction.guild.get_member(int(listing['discord_id']))
                seller_name = seller.display_name if seller else 'Unknown'

                value = (
                    f'💰 ${listing["price"]} | 👁️ {listing["views"]} views\n'
                    f'👤 {seller_name} | ⭐ {listing["average_rating"] or "N/A"}\n'
                    f'🆔 `{listing["id"]}`'
                )
                embed.add_field(name=f'#{i} {listing["emoji"]} {listing["title"][:40]}', value=value, inline=False)

            await safe_send(interaction, embed=embed, ephemeral=False)

        except Exception as e:
            logger.error(f'Featured error: {str(e)}')
            embed = error_embed('Featured Error', 'An error occurred.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='marketstats', description='View marketplace statistics')
    @safe_slash_command(requires_db=True)
    async def marketstats_slash(self, interaction: nextcord.Interaction):
        try:
            stats = await db.fetch_one(
                """SELECT
                   COUNT(*) FILTER (WHERE status = 'active') as active_listings,
                   COUNT(*) FILTER (WHERE status = 'sold') as sold_listings,
                   COUNT(DISTINCT seller_id) as active_sellers,
                   AVG(price) FILTER (WHERE status = 'active') as avg_price
                   FROM marketplace_listings"""
            )

            if stats is None:
                embed = error_embed(
                    'Stats Error', 'Could not retrieve marketplace statistics.', contributor_source=__name__
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

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

            embed = info_embed(title='📊 Marketplace Statistics', contributor_source=__name__)

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
                    user = interaction.guild.get_member(int(seller['discord_id']))
                    name = user.display_name if user else 'Unknown'
                    seller_text += f'#{i} {name}: {seller["total_sales"]} sales\n'
                embed.add_field(name='🏆 Top Sellers', value=seller_text, inline=False)

            await safe_send(interaction, embed=embed, ephemeral=False)

        except Exception as e:
            logger.error(f'Stats error: {str(e)}')
            embed = error_embed('Stats Error', 'An error occurred.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)

    # ==================== PREFIX COMMANDS ====================

    @commands.command(name='search', aliases=['find', 'lookup'])
    async def search_items(self, ctx, *, query: str):
        """Advanced search with filters"""
        try:
            filters = self._parse_search_query(query)
            search_term = filters.get('term', '')
            listings = await self._run_search(filters)

            if not listings:
                await ctx.send('🔍 No items found matching your search. Try different keywords or filters!')
                return

            embed = nextcord.Embed(
                title=f'🔍 Search Results ({len(listings)} items)',
                description=f'Query: **{search_term or "All items"}**',
                color=nextcord.Color.blue(),
            )

            for listing in listings[:10]:
                seller = ctx.guild.get_member(int(listing['discord_id']))
                seller_name = seller.display_name if seller else 'Unknown'

                value = (
                    f'💰 **${listing["price"]}** | {listing["emoji"]} {listing["category_name"]}\n'
                    f'👤 {seller_name} | ⭐ {listing["average_rating"] or "N/A"} | 📦 {listing["total_sales"] or 0} sales\n'
                    f'🆔 `{listing["id"]}` | 👁️ {listing["views"]} views'
                )
                embed.add_field(name=f'{listing["emoji"]} {listing["title"][:50]}', value=value, inline=False)

            if len(listings) > 10:
                embed.set_footer(text=f'Showing 10 of {len(listings)} results.')

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f'Search error: {str(e)}')
            await ctx.send('❌ An error occurred while searching.')

    @commands.command(name='watch', aliases=['track', 'favorite'])
    async def add_to_watchlist(self, ctx, listing_id: str):
        """Add an item to your watchlist"""
        try:
            user = await get_user(str(ctx.author.id))
            listing = await db.fetch_one('SELECT title, price FROM marketplace_listings WHERE id = $1', listing_id)

            if not listing:
                await ctx.send('❌ Listing not found.')
                return

            await db.execute(
                'INSERT INTO marketplace_watchlist (user_id, listing_id) VALUES ($1, $2) ON CONFLICT DO NOTHING',
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
        """View all items you are watching"""
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

    @commands.command(name='offer', aliases=['bid', 'makeoffer'])
    async def make_offer(self, ctx, listing_id: str, price: str, *, message: str = ''):
        """Make an offer on an item"""
        try:
            buyer = await get_user(str(ctx.author.id))

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

            if str(ctx.author.id) == listing['seller_discord_id']:
                await ctx.send("❌ You can't make an offer on your own item!")
                return

            offered_price = InputValidator.validate_price(price)
            if offered_price is None:
                await ctx.send('❌ Invalid price format.')
                return

            if not listing['is_negotiable']:
                await ctx.send('❌ This seller is not accepting offers on this item.')
                return

            is_clean, fraud_reason = await fraud_detector.check_offer(
                listing_id, buyer['id'], listing['seller_id'], Decimal(str(offered_price))
            )

            if not is_clean:
                await ctx.send(f'❌ {fraud_reason}')
                return

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
        """View offers on your listings or offers you have made"""
        try:
            user = await get_user(str(ctx.author.id))

            received_offers = await db.fetch_many(
                """SELECT o.*, l.title, l.price as original_price, u.discord_id as buyer_discord_id
                   FROM marketplace_offers o
                   JOIN marketplace_listings l ON o.listing_id = l.id
                   JOIN users u ON o.buyer_id = u.id
                   WHERE l.seller_id = $1 AND o.status = 'pending' AND o.expires_at > NOW()
                   ORDER BY o.created_at DESC""",
                user['id'],
            )

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

    @commands.command(name='featured', aliases=['hot', 'trending'])
    async def view_featured(self, ctx):
        """View featured and trending listings"""
        try:
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

    @commands.command(name='marketstats', aliases=['marketplace_stats'])
    async def marketplace_stats(self, ctx):
        """View marketplace statistics"""
        try:
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

    # ==================== SHARED LOGIC ====================

    def _parse_search_query(self, query: str) -> dict:
        filters = {}
        parts = query.split('|')
        if parts:
            filters['term'] = parts[0].strip()
        for part in parts[1:]:
            part = part.strip()
            if ':' in part:
                key, value = part.split(':', 1)
                filters[key.strip()] = value.strip()
        return filters

    async def _run_search(self, filters: dict) -> list[dict]:
        search_term = filters.get('term', '')

        sql = """SELECT l.*, u.discord_id, c.name as category_name, c.emoji,
                        s.average_rating, s.total_sales
                 FROM marketplace_listings l
                 JOIN users u ON l.seller_id = u.id
                 JOIN marketplace_categories c ON l.category_id = c.id
                 LEFT JOIN marketplace_seller_stats s ON l.seller_id = s.user_id
                 WHERE l.status = 'active'"""
        params = []
        param_count = 0

        if search_term:
            param_count += 1
            sql += f" AND (to_tsvector('english', l.title) @@ plainto_tsquery('english', ${param_count})"
            sql += f" OR to_tsvector('english', l.description) @@ plainto_tsquery('english', ${param_count})"
            sql += f' OR l.tags && ARRAY[${param_count}])'
            params.append(search_term)

        if 'min_price' in filters:
            param_count += 1
            sql += f' AND l.price >= ${param_count}'
            params.append(Decimal(filters['min_price']))

        if 'max_price' in filters:
            param_count += 1
            sql += f' AND l.price <= ${param_count}'
            params.append(Decimal(filters['max_price']))

        if 'condition' in filters:
            param_count += 1
            sql += f' AND l.condition = ${param_count}'
            params.append(filters['condition'])

        if 'category' in filters:
            param_count += 1
            sql += f' AND LOWER(c.name) = LOWER(${param_count})'
            params.append(filters['category'])

        if 'min_rating' in filters:
            param_count += 1
            sql += f' AND s.average_rating >= ${param_count}'
            params.append(float(filters['min_rating']))

        sort = filters.get('sort', 'newest')
        if sort == 'price_low':
            sql += ' ORDER BY l.price ASC'
        elif sort == 'price_high':
            sql += ' ORDER BY l.price DESC'
        elif sort == 'popular':
            sql += ' ORDER BY l.views DESC'
        else:
            sql += ' ORDER BY l.created_at DESC'

        sql += ' LIMIT 20'
        return await db.fetch_many(sql, *params)

    # ==================== BACKGROUND TASKS ====================

    @tasks.loop(hours=6)
    async def check_price_drops(self):
        try:
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
        logger.info('Updated featured listings cache')

    @tasks.loop(hours=24)
    async def check_expiring_listings(self):
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


def setup(bot):
    bot.add_cog(MarketplaceEnhanced(bot))
