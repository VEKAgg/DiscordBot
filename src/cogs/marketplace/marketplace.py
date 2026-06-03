"""
Marketplace Cog - Discord Ecommerce System
Allows users to buy and sell items within Discord
"""

import asyncio
import nextcord
from nextcord.ext import commands
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.database.database import db, get_user
from src.utils.security import (
    rate_limit, require_verified, audit_action,
    sanitize, InputValidator
)
from src.utils.marketplace.fraud_detection import fraud_detector

logger = logging.getLogger('VEKA.marketplace')

class Marketplace(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.group(name="marketplace", aliases=["mp", "shop"], invoke_without_command=True)
    async def marketplace(self, ctx):
        """Marketplace commands for buying and selling"""
        if ctx.invoked_subcommand is None:
            embed = nextcord.Embed(
                title="🏪 Marketplace Commands",
                description="Buy and sell items with other members!",
                color=nextcord.Color.blue()
            )
            embed.add_field(
                name="Selling",
                value="`!marketplace post` - Create a new listing\n"
                      "`!marketplace mylistings` - View your listings",
                inline=False
            )
            embed.add_field(
                name="Buying",
                value="`!marketplace browse [category]` - Browse listings\n"
                      "`!marketplace search <query>` - Search items\n"
                      "`!marketplace view <id>` - View item details\n"
                      "`!marketplace buy <id>` - Purchase an item",
                inline=False
            )
            embed.add_field(
                name="Management",
                value="`!marketplace watch <id>` - Add to watchlist\n"
                      "`!marketplace unwatch <id>` - Remove from watchlist\n"
                      "`!marketplace withdraw <id>` - Remove your listing",
                inline=False
            )
            await ctx.send(embed=embed)
    
    @rate_limit('marketplace')
    @require_verified()
    @audit_action('marketplace_listing_created')
    @marketplace.command(name="post", aliases=["sell", "create"])
    async def post_listing(self, ctx):
        """Create a new marketplace listing (interactive)"""
        try:
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel
            
            # Get categories
            categories = await db.fetch_many(
                "SELECT id, name, emoji FROM marketplace_categories WHERE is_active = TRUE ORDER BY name"
            )
            
            # Show categories
            cat_list = "\n".join([f"{c['emoji']} {c['name']}" for c in categories])
            await ctx.send(f"📁 **Select a category:**\n{cat_list}\n\nReply with the category name:")
            
            cat_msg = await self.bot.wait_for('message', check=check, timeout=60)
            category_name = cat_msg.content.strip()
            
            category = await db.fetch_one(
                "SELECT id FROM marketplace_categories WHERE LOWER(name) = LOWER($1)",
                category_name
            )
            
            if not category:
                await ctx.send("❌ Invalid category. Please try again.")
                return
            
            # Get title
            await ctx.send("📝 **Enter item title** (max 100 characters):")
            title_msg = await self.bot.wait_for('message', check=check, timeout=60)
            title = sanitize(title_msg.content, max_length=100)
            
            if len(title) < 3:
                await ctx.send("❌ Title must be at least 3 characters.")
                return
            
            # Get description
            await ctx.send("📄 **Enter item description** (min 10, max 1000 characters):")
            desc_msg = await self.bot.wait_for('message', check=check, timeout=120)
            description = sanitize(desc_msg.content, max_length=1000)
            
            if len(description) < 10:
                await ctx.send("❌ Description must be at least 10 characters.")
                return
            
            # Get price
            await ctx.send("💰 **Enter price** (e.g., 99.99):")
            price_msg = await self.bot.wait_for('message', check=check, timeout=60)
            price = InputValidator.validate_price(price_msg.content)
            
            if price is None:
                await ctx.send("❌ Invalid price format. Please use format like '99.99'")
                return
            
            # Get condition
            conditions = ["new", "like_new", "good", "fair", "poor"]
            await ctx.send(
                "📦 **Select condition:**\n"
                "• **New** - Brand new, sealed\n"
                "• **Like New** - Used once or twice, perfect condition\n"
                "• **Good** - Normal wear, works perfectly\n"
                "• **Fair** - Visible wear but functional\n"
                "• **Poor** - Heavy wear, may have issues\n\n"
                f"Reply with: {', '.join(conditions)}"
            )
            
            cond_msg = await self.bot.wait_for('message', check=check, timeout=60)
            condition = cond_msg.content.lower().strip()
            
            if condition not in conditions:
                await ctx.send("❌ Invalid condition.")
                return
            
            # Validate with fraud detection
            seller = await get_user(str(ctx.author.id))
            is_clean, warnings = await fraud_detector.check_listing(
                seller['id'], Decimal(str(price)), condition, category['id']
            )
            
            if not is_clean:
                warning_msg = "\n".join([f"⚠️ {w}" for w in warnings])
                await ctx.send(
                    f"⚠️ **Your listing has been flagged for review:**\n{warning_msg}\n\n"
                    f"A moderator will review your listing shortly."
                )
                status = 'pending_review'
            else:
                status = 'active'
            
            # Validate marketplace item
            validation = InputValidator.validate_marketplace_item(title, description, price)
            if not validation['valid']:
                await ctx.send(f"❌ **Validation failed:**\n" + "\n".join(validation['errors']))
                return
            
            # Create listing
            listing_id = f"MP{int(datetime.utcnow().timestamp())}"
            
            await db.execute(
                """INSERT INTO marketplace_listings 
                   (id, seller_id, title, description, price, category_id, condition, status)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                listing_id, seller['id'], title, description, price, 
                category['id'], condition, status
            )
            
            # Update seller stats
            await db.execute(
                """INSERT INTO marketplace_seller_stats (user_id, active_listings)
                   VALUES ($1, 1)
                   ON CONFLICT (user_id) 
                   DO UPDATE SET active_listings = marketplace_seller_stats.active_listings + 1""",
                seller['id']
            )
            
            embed = nextcord.Embed(
                title="✅ Listing Created!" if status == 'active' else "⏳ Listing Pending Review",
                description=f"**{title}**\n💰 ${price}",
                color=nextcord.Color.green() if status == 'active' else nextcord.Color.orange()
            )
            embed.add_field(name="ID", value=f"`{listing_id}`", inline=True)
            embed.add_field(name="Status", value=status.replace('_', ' ').title(), inline=True)
            embed.add_field(name="View", value=f"`!marketplace view {listing_id}`", inline=False)
            
            await ctx.send(embed=embed)
            
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Listing creation timed out. Please try again.")
        except Exception as e:
            logger.error(f"Error creating listing: {str(e)}")
            await ctx.send("❌ An error occurred while creating your listing.")
    
    @marketplace.command(name="browse", aliases=["list", "show"])
    async def browse_listings(self, ctx, category: Optional[str] = None):
        """Browse active marketplace listings"""
        try:
            if category:
                # Filter by category
                listings = await db.fetch_many(
                    """SELECT l.*, u.discord_id, c.name as category_name, c.emoji
                       FROM marketplace_listings l
                       JOIN users u ON l.seller_id = u.id
                       JOIN marketplace_categories c ON l.category_id = c.id
                       WHERE l.status = 'active'
                       AND LOWER(c.name) = LOWER($1)
                       ORDER BY l.created_at DESC
                       LIMIT 10""",
                    category
                )
            else:
                # Show all recent listings
                listings = await db.fetch_many(
                    """SELECT l.*, u.discord_id, c.name as category_name, c.emoji
                       FROM marketplace_listings l
                       JOIN users u ON l.seller_id = u.id
                       JOIN marketplace_categories c ON l.category_id = c.id
                       WHERE l.status = 'active'
                       ORDER BY l.created_at DESC
                       LIMIT 10"""
                )
            
            if not listings:
                await ctx.send("📭 No active listings found. Be the first to sell something!")
                return
            
            embed = nextcord.Embed(
                title="🏪 Marketplace Listings",
                description=f"Showing {len(listings)} active item(s)",
                color=nextcord.Color.blue()
            )
            
            for listing in listings:
                seller = ctx.guild.get_member(int(listing['discord_id']))
                seller_name = seller.display_name if seller else "Unknown"
                
                value = (
                    f"💰 **${listing['price']}** | {listing['emoji']} {listing['category_name']}\n"
                    f"👤 {seller_name} | 📦 {listing['condition'].replace('_', ' ').title()}\n"
                    f"🆔 `{listing['id']}` | 👁️ {listing['views']} views"
                )
                
                embed.add_field(
                    name=f"{listing['emoji']} {listing['title'][:50]}",
                    value=value,
                    inline=False
                )
            
            embed.set_footer(text="Use !marketplace view <id> for details")
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error browsing listings: {str(e)}")
            await ctx.send("❌ An error occurred while fetching listings.")
    
    @marketplace.command(name="view", aliases=["show"])
    async def view_listing(self, ctx, listing_id: str):
        """View details of a specific listing"""
        try:
            # Update view count
            await db.execute(
                "UPDATE marketplace_listings SET views = views + 1 WHERE id = $1",
                listing_id
            )
            
            listing = await db.fetch_one(
                """SELECT l.*, u.discord_id, c.name as category_name, c.emoji,
                       s.average_rating, s.review_count, s.total_sales
                   FROM marketplace_listings l
                   JOIN users u ON l.seller_id = u.id
                   JOIN marketplace_categories c ON l.category_id = c.id
                   LEFT JOIN marketplace_seller_stats s ON l.seller_id = s.user_id
                   WHERE l.id = $1""",
                listing_id
            )
            
            if not listing:
                await ctx.send("❌ Listing not found.")
                return
            
            seller = ctx.guild.get_member(int(listing['discord_id']))
            seller_name = seller.display_name if seller else "Unknown"
            
            embed = nextcord.Embed(
                title=f"{listing['emoji']} {listing['title']}",
                description=listing['description'][:1000],
                color=nextcord.Color.blue()
            )
            
            embed.add_field(name="💰 Price", value=f"${listing['price']}", inline=True)
            embed.add_field(name="📦 Condition", value=listing['condition'].replace('_', ' ').title(), inline=True)
            embed.add_field(name="📁 Category", value=f"{listing['emoji']} {listing['category_name']}", inline=True)
            
            # Seller info
            rating_text = f"⭐ {listing['average_rating']:.1f} ({listing['review_count']} reviews)" if listing['average_rating'] else "No reviews yet"
            embed.add_field(
                name="👤 Seller",
                value=f"{seller_name}\n{rating_text}\n📦 {listing['total_sales'] or 0} sales",
                inline=False
            )
            
            embed.add_field(name="👁️ Views", value=listing['views'], inline=True)
            embed.add_field(name="🆔 ID", value=f"`{listing['id']}`", inline=True)
            
            if listing['status'] == 'active':
                embed.add_field(
                    name="🛒 Purchase",
                    value=f"Use `!marketplace buy {listing['id']}`",
                    inline=False
                )
            else:
                embed.add_field(name="Status", value=listing['status'].replace('_', ' ').title(), inline=False)
            
            if seller:
                embed.set_thumbnail(url=seller.avatar.url if seller.avatar else seller.default_avatar.url)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error viewing listing: {str(e)}")
            await ctx.send("❌ An error occurred while fetching the listing.")
    
    @rate_limit('marketplace')
    @require_verified()
    @marketplace.command(name="buy", aliases=["purchase"])
    async def buy_item(self, ctx, listing_id: str):
        """Purchase an item from the marketplace"""
        try:
            # Check if user is blocked
            buyer = await get_user(str(ctx.author.id))
            is_blocked, block_reason = await fraud_detector.is_user_blocked(buyer['id'])
            
            if is_blocked:
                await ctx.send(f"❌ {block_reason}")
                return
            
            # Get listing
            listing = await db.fetch_one(
                """SELECT l.*, u.discord_id as seller_discord_id
                   FROM marketplace_listings l
                   JOIN users u ON l.seller_id = u.id
                   WHERE l.id = $1 AND l.status = 'active'""",
                listing_id
            )
            
            if not listing:
                await ctx.send("❌ Listing not found or no longer available.")
                return
            
            # Prevent buying own item
            if str(ctx.author.id) == listing['seller_discord_id']:
                await ctx.send("❌ You cannot buy your own item!")
                return
            
            # Fraud detection
            is_clean, fraud_reason = await fraud_detector.check_purchase(
                buyer['id'], listing['seller_id'], listing_id, listing['price']
            )
            
            if not is_clean:
                await ctx.send(f"❌ {fraud_reason}")
                return
            
            # Create transaction
            transaction_id = await db.fetch_one(
                """INSERT INTO marketplace_transactions 
                   (listing_id, buyer_id, seller_id, agreed_price, status)
                   VALUES ($1, $2, $3, $4, 'pending')
                   RETURNING id""",
                listing_id, buyer['id'], listing['seller_id'], listing['price']
            )
            
            # Update listing status
            await db.execute(
                "UPDATE marketplace_listings SET status = 'pending' WHERE id = $1",
                listing_id
            )
            
            # Get seller
            seller = ctx.guild.get_member(int(listing['seller_discord_id']))
            
            embed = nextcord.Embed(
                title="🛒 Purchase Initiated",
                description=f"**{listing['title']}**\n💰 ${listing['price']}",
                color=nextcord.Color.orange()
            )
            embed.add_field(name="Transaction ID", value=f"`{transaction_id['id']}`", inline=True)
            embed.add_field(name="Seller", value=seller.mention if seller else "Unknown", inline=True)
            embed.add_field(
                name="Next Steps",
                value=f"1. Contact the seller to arrange payment\n"
                      f"2. Use a secure payment method\n"
                      f"3. Confirm receipt with `!marketplace confirm {transaction_id['id']}`",
                inline=False
            )
            
            await ctx.send(embed=embed)
            
            # Notify seller
            if seller:
                try:
                    seller_embed = nextcord.Embed(
                        title="🛒 New Purchase Request!",
                        description=f"**{listing['title']}** has been requested by {ctx.author.display_name}",
                        color=nextcord.Color.green()
                    )
                    seller_embed.add_field(name="Price", value=f"${listing['price']}", inline=True)
                    seller_embed.add_field(name="Transaction ID", value=f"`{transaction_id['id']}`", inline=True)
                    await seller.send(embed=seller_embed)
                except:
                    pass
            
        except Exception as e:
            logger.error(f"Error purchasing item: {str(e)}")
            await ctx.send("❌ An error occurred while processing the purchase.")
    
    @marketplace.command(name="mylistings", aliases=["myposts"])
    async def my_listings(self, ctx):
        """View your marketplace listings"""
        try:
            user = await get_user(str(ctx.author.id))
            
            listings = await db.fetch_many(
                """SELECT l.*, c.name as category_name, c.emoji
                   FROM marketplace_listings l
                   JOIN marketplace_categories c ON l.category_id = c.id
                   WHERE l.seller_id = $1
                   ORDER BY l.created_at DESC""",
                user['id']
            )
            
            if not listings:
                await ctx.send("📭 You don't have any listings. Create one with `!marketplace post`")
                return
            
            embed = nextcord.Embed(
                title="📦 Your Listings",
                description=f"You have {len(listings)} listing(s)",
                color=nextcord.Color.blue()
            )
            
            for listing in listings:
                status_emoji = "🟢" if listing['status'] == 'active' else "🟡" if listing['status'] == 'pending' else "🔴"
                
                value = (
                    f"{status_emoji} **{listing['status'].replace('_', ' ').title()}**\n"
                    f"💰 ${listing['price']} | 👁️ {listing['views']} views\n"
                    f"📦 {listing['condition'].replace('_', ' ').title()}"
                )
                
                embed.add_field(
                    name=f"{listing['emoji']} {listing['title'][:50]}",
                    value=value,
                    inline=False
                )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error fetching user listings: {str(e)}")
            await ctx.send("❌ An error occurred while fetching your listings.")
    
    @marketplace.command(name="withdraw", aliases=["remove", "delete"])
    async def withdraw_listing(self, ctx, listing_id: str):
        """Withdraw your listing from the marketplace"""
        try:
            user = await get_user(str(ctx.author.id))
            
            # Verify ownership
            listing = await db.fetch_one(
                """SELECT seller_id, status, title FROM marketplace_listings WHERE id = $1""",
                listing_id
            )
            
            if not listing:
                await ctx.send("❌ Listing not found.")
                return
            
            if listing['seller_id'] != user['id']:
                await ctx.send("❌ You can only withdraw your own listings.")
                return
            
            if listing['status'] == 'sold':
                await ctx.send("❌ Cannot withdraw a sold item.")
                return
            
            # Update status
            await db.execute(
                "UPDATE marketplace_listings SET status = 'withdrawn' WHERE id = $1",
                listing_id
            )
            
            # Update seller stats
            await db.execute(
                """UPDATE marketplace_seller_stats 
                   SET active_listings = active_listings - 1 
                   WHERE user_id = $1""",
                user['id']
            )
            
            await ctx.send(f"✅ **{listing['title']}** has been withdrawn from the marketplace.")
            
        except Exception as e:
            logger.error(f"Error withdrawing listing: {str(e)}")
            await ctx.send("❌ An error occurred while withdrawing the listing.")

def setup(bot):
    bot.add_cog(Marketplace(bot))
