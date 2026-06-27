"""
Marketplace Reviews and Reputation System
Build trust and encourage quality transactions
"""

import logging
from datetime import datetime, timedelta

import nextcord
from nextcord.ext import commands

from src.database.database import db, get_user
from src.utils.security import rate_limit, sanitize

logger = logging.getLogger('VEKA.marketplace.reviews')


class MarketplaceReviews(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='review', aliases=['rate', 'feedback'])
    async def leave_review(self, ctx, transaction_id: int, rating: int, *, comment: str = ''):
        """
        Leave a review for a transaction
        Usage: !review <transaction_id> <1-5> [comment]
        Example: !review 123 5 Great seller, fast shipping!
        """
        try:
            if rating < 1 or rating > 5:
                await ctx.send('❌ Rating must be between 1 and 5 stars.')
                return

            user = await get_user(str(ctx.author.id))

            # Get transaction
            transaction = await db.fetch_one(
                """SELECT t.*, l.title, u_seller.discord_id as seller_discord_id,
                          u_buyer.discord_id as buyer_discord_id
                   FROM marketplace_transactions t
                   JOIN marketplace_listings l ON t.listing_id = l.id
                   JOIN users u_seller ON t.seller_id = u_seller.id
                   JOIN users u_buyer ON t.buyer_id = u_buyer.id
                   WHERE t.id = $1 AND t.status = 'completed'""",
                transaction_id,
            )

            if not transaction:
                await ctx.send('❌ Transaction not found or not completed yet.')
                return

            # Determine who is reviewing whom
            if str(ctx.author.id) == transaction['buyer_discord_id']:
                # Buyer reviewing seller
                reviewee_id = transaction['seller_id']
                is_buyer_review = True
            elif str(ctx.author.id) == transaction['seller_discord_id']:
                # Seller reviewing buyer
                reviewee_id = transaction['buyer_id']
                is_buyer_review = False
            else:
                await ctx.send('❌ You can only review transactions you participated in.')
                return

            # Check if already reviewed
            existing = await db.fetch_one(
                """SELECT id FROM marketplace_reviews
                   WHERE transaction_id = $1 AND reviewer_id = $2""",
                transaction_id,
                user['id'],
            )

            if existing:
                await ctx.send("❌ You've already reviewed this transaction.")
                return

            # Sanitize comment
            safe_comment = sanitize(comment, max_length=500)

            # Create review
            await db.execute(
                """INSERT INTO marketplace_reviews
                   (transaction_id, reviewer_id, reviewee_id, rating, comment, is_buyer_review)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                transaction_id,
                user['id'],
                reviewee_id,
                rating,
                safe_comment,
                is_buyer_review,
            )

            # Update seller stats
            await self._update_seller_stats(reviewee_id)

            await ctx.send(f'✅ Review submitted! {rating}/5 ⭐')

            # Notify reviewee
            reviewee_discord_id = (
                transaction['seller_discord_id'] if is_buyer_review else transaction['buyer_discord_id']
            )
            reviewee = self.bot.get_user(int(reviewee_discord_id))

            if reviewee:
                try:
                    role = 'buyer' if is_buyer_review else 'seller'
                    embed = nextcord.Embed(
                        title='⭐ New Review Received!',
                        description=f'A {role} left you a {rating}/5 star review for **{transaction["title"]}**',
                        color=nextcord.Color.gold(),
                    )
                    if safe_comment:
                        embed.add_field(name='Comment', value=safe_comment[:500], inline=False)
                    await reviewee.send(embed=embed)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f'Review error: {str(e)}')
            await ctx.send('❌ An error occurred while submitting the review.')

    async def _update_seller_stats(self, user_id: int):
        """Update cached seller statistics"""
        try:
            stats = await db.fetch_one(
                """SELECT
                   COUNT(*) FILTER (WHERE is_buyer_review = TRUE) as review_count,
                   AVG(rating) FILTER (WHERE is_buyer_review = TRUE) as avg_rating
                   FROM marketplace_reviews
                   WHERE reviewee_id = $1""",
                user_id,
            )

            sales = await db.fetch_one(
                """SELECT COUNT(*) as total_sales
                   FROM marketplace_transactions
                   WHERE seller_id = $1 AND status = 'completed'""",
                user_id,
            )

            revenue = await db.fetch_one(
                """SELECT SUM(agreed_price) as total_revenue
                   FROM marketplace_transactions
                   WHERE seller_id = $1 AND status = 'completed'""",
                user_id,
            )

            await db.execute(
                """INSERT INTO marketplace_seller_stats
                   (user_id, total_sales, total_revenue, average_rating, review_count)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (user_id)
                   DO UPDATE SET
                   total_sales = $2,
                   total_revenue = $3,
                   average_rating = $4,
                   review_count = $5,
                   updated_at = NOW()""",
                user_id,
                sales['total_sales'] if sales else 0,
                revenue['total_revenue'] if revenue else 0,
                stats['avg_rating'] if stats else 0,
                stats['review_count'] if stats else 0,
            )
        except Exception as e:
            logger.error(f'Error updating seller stats: {str(e)}')

    @commands.command(name='seller', aliases=['sellerprofile', 'reputation'])
    async def view_seller_profile(self, ctx, member: nextcord.Member = None):
        """View a seller's reputation and statistics"""
        try:
            target = member or ctx.author
            user = await get_user(str(target.id))

            stats = await db.fetch_one("""SELECT * FROM marketplace_seller_stats WHERE user_id = $1""", user['id'])

            if not stats or stats['total_sales'] == 0:
                await ctx.send(f"📭 {target.display_name} hasn't made any sales yet.")
                return

            # Get recent reviews
            reviews = await db.fetch_many(
                """SELECT r.*, l.title, u.discord_id as reviewer_discord_id
                   FROM marketplace_reviews r
                   JOIN marketplace_transactions t ON r.transaction_id = t.id
                   JOIN marketplace_listings l ON t.listing_id = l.id
                   JOIN users u ON r.reviewer_id = u.id
                   WHERE r.reviewee_id = $1 AND r.is_buyer_review = TRUE
                   ORDER BY r.created_at DESC
                   LIMIT 5""",
                user['id'],
            )

            embed = nextcord.Embed(title=f"🏪 {target.display_name}'s Seller Profile", color=nextcord.Color.blue())
            embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)

            # Stats
            stars = '⭐' * int(stats['average_rating']) if stats['average_rating'] else 'No ratings'
            embed.add_field(
                name='📊 Statistics',
                value=(
                    f'⭐ Rating: **{stats["average_rating"]:.1f}** ({stats["review_count"]} reviews)\n'
                    f'📦 Sales: **{stats["total_sales"]}**\n'
                    f'💰 Revenue: **${stats["total_revenue"]:.2f}**\n'
                    f'📋 Active: **{stats["active_listings"]}** listings'
                ),
                inline=False,
            )

            # Recent reviews
            if reviews:
                reviews_text = ''
                for review in reviews:
                    reviewer = ctx.guild.get_member(int(review['reviewer_discord_id']))
                    name = reviewer.display_name if reviewer else 'Unknown'
                    stars = '⭐' * review['rating']
                    comment = (
                        review['comment'][:50] + '...'
                        if review['comment'] and len(review['comment']) > 50
                        else (review['comment'] or 'No comment')
                    )
                    reviews_text += f'{stars} **{name}**: {comment}\n'

                embed.add_field(name='📝 Recent Reviews', value=reviews_text, inline=False)

            # Active listings
            active = await db.fetch_many(
                """SELECT id, title, price, emoji
                   FROM marketplace_listings l
                   JOIN marketplace_categories c ON l.category_id = c.id
                   WHERE seller_id = $1 AND status = 'active'
                   ORDER BY created_at DESC
                   LIMIT 3""",
                user['id'],
            )

            if active:
                listings_text = '\n'.join(
                    [f'{item["emoji"]} {item["title"][:30]} - ${item["price"]}' for item in active]
                )
                embed.add_field(name='📦 Active Listings', value=listings_text, inline=False)

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f'Seller profile error: {str(e)}')
            await ctx.send('❌ An error occurred.')

    @commands.command(name='reviews', aliases=['myreviews'])
    async def view_my_reviews(self, ctx):
        """View reviews you've received"""
        try:
            user = await get_user(str(ctx.author.id))

            reviews = await db.fetch_many(
                """SELECT r.*, l.title, u.discord_id as reviewer_discord_id
                   FROM marketplace_reviews r
                   JOIN marketplace_transactions t ON r.transaction_id = t.id
                   JOIN marketplace_listings l ON t.listing_id = l.id
                   JOIN users u ON r.reviewer_id = u.id
                   WHERE r.reviewee_id = $1
                   ORDER BY r.created_at DESC
                   LIMIT 10""",
                user['id'],
            )

            if not reviews:
                await ctx.send("📭 You haven't received any reviews yet.")
                return

            embed = nextcord.Embed(
                title='📝 Your Reviews',
                description=f"You've received {len(reviews)} review(s)",
                color=nextcord.Color.blue(),
            )

            for review in reviews[:5]:
                reviewer = ctx.guild.get_member(int(review['reviewer_discord_id']))
                name = reviewer.display_name if reviewer else 'Unknown'
                stars = '⭐' * review['rating']
                role = 'Buyer' if review['is_buyer_review'] else 'Seller'

                value = f'{stars} ({role})\n{review["comment"][:200] if review["comment"] else "No comment"}'

                embed.add_field(name=f'For: {review["title"][:30]} - {name}', value=value, inline=False)

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f'View reviews error: {str(e)}')
            await ctx.send('❌ An error occurred.')

    @commands.command(name='helpful', aliases=['vote'])
    async def mark_review_helpful(self, ctx, review_id: int):
        """Mark a review as helpful"""
        try:
            await db.execute(
                """INSERT INTO marketplace_review_votes (review_id, user_id, is_helpful)
                   VALUES ($1, $2, TRUE)
                   ON CONFLICT DO NOTHING""",
                review_id,
                ctx.author.id,
            )

            # Update helpful count
            await db.execute(
                """UPDATE marketplace_reviews
                   SET helpful_count = (SELECT COUNT(*) FROM marketplace_review_votes WHERE review_id = $1)
                   WHERE id = $1""",
                review_id,
            )

            await ctx.send('✅ Thanks for your feedback!')

        except Exception as e:
            logger.error(f'Helpful vote error: {str(e)}')
            await ctx.send('❌ An error occurred.')

    @commands.command(name='bump', aliases=['refresh', 'renew'])
    @rate_limit('marketplace')
    async def bump_listing(self, ctx, listing_id: str):
        """Bump your listing to the top (once per day per listing)"""
        try:
            user = await get_user(str(ctx.author.id))

            # Verify ownership
            listing = await db.fetch_one(
                """SELECT seller_id, title, bumped_at
                   FROM marketplace_listings
                   WHERE id = $1 AND status = 'active'""",
                listing_id,
            )

            if not listing:
                await ctx.send('❌ Listing not found or not active.')
                return

            if listing['seller_id'] != user['id']:
                await ctx.send('❌ You can only bump your own listings.')
                return

            # Check if bumped recently
            if listing['bumped_at'] and listing['bumped_at'] > datetime.utcnow() - timedelta(hours=24):
                time_left = listing['bumped_at'] + timedelta(hours=24) - datetime.utcnow()
                hours = int(time_left.total_seconds() // 3600)
                await ctx.send(f'⏱️ You can bump this listing again in {hours} hours.')
                return

            # Bump the listing (update timestamp)
            await db.execute('UPDATE marketplace_listings SET bumped_at = NOW() WHERE id = $1', listing_id)

            await ctx.send(f'✅ **{listing["title"]}** has been bumped to the top!')

        except Exception as e:
            logger.error(f'Bump error: {str(e)}')
            await ctx.send('❌ An error occurred.')


def setup(bot):
    bot.add_cog(MarketplaceReviews(bot))
