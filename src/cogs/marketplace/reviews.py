"""
Marketplace Reviews and Reputation System
Build trust and encourage quality transactions
"""

import logging

import nextcord
from nextcord.ext import commands

from src.database.database import db, get_user
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import safe_send, safe_slash_command
from src.utils.security import rate_limit, sanitize

logger = logging.getLogger('VEKA.marketplace.reviews')


class MarketplaceReviews(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ==================== SLASH COMMANDS (delegated via /marketplace group) ====================

    async def review_slash(
        self,
        interaction: nextcord.Interaction,
        transaction_id: int,
        rating: int = nextcord.SlashOption(description='Rating from 1 to 5', min_value=1, max_value=5),
        comment: str = '',
    ):
        try:
            user = await get_user(str(interaction.user.id))

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
                embed = await error_embed(
                    'Not Found',
                    'Transaction not found or not completed yet.',
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            if str(interaction.user.id) == transaction['buyer_discord_id']:
                reviewee_id = transaction['seller_id']
                is_buyer_review = True
            elif str(interaction.user.id) == transaction['seller_discord_id']:
                reviewee_id = transaction['buyer_id']
                is_buyer_review = False
            else:
                embed = await error_embed(
                    'Not Allowed',
                    'You can only review transactions you participated in.',
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            existing = await db.fetch_one(
                'SELECT id FROM marketplace_reviews WHERE transaction_id = $1 AND reviewer_id = $2',
                transaction_id,
                user['id'],
            )

            if existing:
                embed = await error_embed(
                    'Already Reviewed',
                    "You've already reviewed this transaction.",
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            safe_comment = sanitize(comment, max_length=500)

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

            await self._update_seller_stats(reviewee_id)

            embed = await success_embed(
                title='Review Submitted',
                description=f'{rating}/5 ⭐',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

            reviewee_discord_id = (
                transaction['seller_discord_id'] if is_buyer_review else transaction['buyer_discord_id']
            )
            reviewee = self.bot.get_user(int(reviewee_discord_id))

            if reviewee:
                try:
                    role = 'buyer' if is_buyer_review else 'seller'
                    notify = await info_embed(
                        title='⭐ New Review Received!',
                        description=f'A {role} left you a {rating}/5 star review for **{transaction["title"]}**',
                        contributor_source=__name__,
                        user=interaction.user,
                    )
                    if safe_comment:
                        notify.add_field(name='Comment', value=safe_comment[:500], inline=False)
                    await reviewee.send(embed=notify)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f'Review error: {str(e)}')
            embed = await error_embed(
                'Review Error',
                'An error occurred while submitting the review.',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    async def seller_slash(self, interaction: nextcord.Interaction, member: nextcord.Member = None):
        try:
            target = member or interaction.user
            user = await get_user(str(target.id))

            stats = await db.fetch_one('SELECT * FROM marketplace_seller_stats WHERE user_id = $1', user['id'])

            if not stats or stats['total_sales'] == 0:
                embed = await info_embed(
                    title='No Sales',
                    description=f"{target.display_name} hasn't made any sales yet.",
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

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

            embed = await info_embed(
                title=f"🏪 {target.display_name}'s Seller Profile", contributor_source=__name__, user=interaction.user
            )
            embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)

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

            if reviews:
                reviews_text = ''
                for review in reviews:
                    reviewer = interaction.guild.get_member(int(review['reviewer_discord_id']))
                    name = reviewer.display_name if reviewer else 'Unknown'
                    stars = '⭐' * review['rating']
                    comment_text = (
                        review['comment'][:50] + '...'
                        if review['comment'] and len(review['comment']) > 50
                        else (review['comment'] or 'No comment')
                    )
                    reviews_text += f'{stars} **{name}**: {comment_text}\n'
                embed.add_field(name='📝 Recent Reviews', value=reviews_text, inline=False)

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

            await safe_send(interaction, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'Seller profile error: {str(e)}')
            embed = await error_embed(
                'Seller Error', 'An error occurred.', contributor_source=__name__, user=interaction.user
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    async def reviews_slash(self, interaction: nextcord.Interaction):
        try:
            user = await get_user(str(interaction.user.id))

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
                embed = await info_embed(
                    title='No Reviews',
                    description="You haven't received any reviews yet.",
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            embed = await info_embed(
                title='📝 Your Reviews',
                description=f"You've received {len(reviews)} review(s)",
                contributor_source=__name__,
                user=interaction.user,
            )

            for review in reviews[:5]:
                reviewer = interaction.guild.get_member(int(review['reviewer_discord_id']))
                name = reviewer.display_name if reviewer else 'Unknown'
                stars = '⭐' * review['rating']
                role = 'Buyer' if review['is_buyer_review'] else 'Seller'

                value = f'{stars} ({role})\n{review["comment"][:200] if review["comment"] else "No comment"}'
                embed.add_field(name=f'For: {review["title"][:30]} - {name}', value=value, inline=False)

            await safe_send(interaction, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'View reviews error: {str(e)}')
            embed = await error_embed(
                'Reviews Error', 'An error occurred.', contributor_source=__name__, user=interaction.user
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    async def helpful_slash(self, interaction: nextcord.Interaction, review_id: int):
        try:
            await db.execute(
                """INSERT INTO marketplace_review_votes (review_id, user_id, is_helpful)
                   VALUES ($1, $2, TRUE)
                   ON CONFLICT DO NOTHING""",
                review_id,
                interaction.user.id,
            )

            await db.execute(
                """UPDATE marketplace_reviews
                   SET helpful_count = (SELECT COUNT(*) FROM marketplace_review_votes WHERE review_id = $1)
                   WHERE id = $1""",
                review_id,
            )

            embed = await success_embed(
                title='Thanks!',
                description='Thanks for your feedback!',
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'Helpful vote error: {str(e)}')
            embed = await error_embed(
                'Vote Error', 'An error occurred.', contributor_source=__name__, user=interaction.user
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    @nextcord.slash_command(name='bump', description='Bump your listing to the top (once per day)')
    @rate_limit('marketplace')
    @safe_slash_command(requires_db=True)
    async def bump_slash(self, interaction: nextcord.Interaction, listing_id: str):
        try:
            user = await get_user(str(interaction.user.id))

            listing = await db.fetch_one(
                "SELECT seller_id, title, bumped_at FROM marketplace_listings WHERE id = $1 AND status = 'active'",
                listing_id,
            )

            if not listing:
                embed = await error_embed(
                    'Not Found', 'Listing not found or not active.', contributor_source=__name__, user=interaction.user
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            if listing['seller_id'] != user['id']:
                embed = await error_embed(
                    'Not Allowed',
                    'You can only bump your own listings.',
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            from datetime import datetime, timedelta

            if listing['bumped_at'] and listing['bumped_at'] > datetime.utcnow() - timedelta(hours=24):
                time_left = listing['bumped_at'] + timedelta(hours=24) - datetime.utcnow()
                hours = int(time_left.total_seconds() // 3600)
                embed = await error_embed(
                    'Too Soon',
                    f'You can bump this listing again in {hours} hours.',
                    contributor_source=__name__,
                    user=interaction.user,
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

            await db.execute('UPDATE marketplace_listings SET bumped_at = NOW() WHERE id = $1', listing_id)

            embed = await success_embed(
                title='Listing Bumped',
                description=(
                    f'**{listing["title"]}** has been bumped to the top!\n\n'
                    'Also bump with our partner bots to reach even more people:\n'
                    f'\u2022 <@302050872383242240> — Discord Bump Bot\n'
                    f'\u2022 <@1222548162741538938> — Discadia Bot'
                ),
                contributor_source=__name__,
                user=interaction.user,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'Bump error: {str(e)}')
            embed = await error_embed(
                'Bump Error', 'An error occurred.', contributor_source=__name__, user=interaction.user
            )
            await safe_send(interaction, embed=embed, ephemeral=True)

    # ==================== PREFIX COMMANDS ====================

    @commands.command(name='review', aliases=['rate', 'feedback'])
    @rate_limit('marketplace')
    async def leave_review(self, ctx, transaction_id: int, rating: int, *, comment: str = ''):
        """Leave a review for a transaction"""
        try:
            if rating < 1 or rating > 5:
                await ctx.send('❌ Rating must be between 1 and 5 stars.')
                return

            user = await get_user(str(ctx.author.id))

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

            if str(ctx.author.id) == transaction['buyer_discord_id']:
                reviewee_id = transaction['seller_id']
                is_buyer_review = True
            elif str(ctx.author.id) == transaction['seller_discord_id']:
                reviewee_id = transaction['buyer_id']
                is_buyer_review = False
            else:
                await ctx.send('❌ You can only review transactions you participated in.')
                return

            existing = await db.fetch_one(
                'SELECT id FROM marketplace_reviews WHERE transaction_id = $1 AND reviewer_id = $2',
                transaction_id,
                user['id'],
            )

            if existing:
                await ctx.send("❌ You've already reviewed this transaction.")
                return

            safe_comment = sanitize(comment, max_length=500)

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

            await self._update_seller_stats(reviewee_id)

            await ctx.send(f'✅ Review submitted! {rating}/5 ⭐')

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

    @commands.command(name='seller', aliases=['sellerprofile', 'reputation'])
    async def view_seller_profile(self, ctx, member: nextcord.Member = None):
        """View a seller's reputation and statistics"""
        try:
            target = member or ctx.author
            user = await get_user(str(target.id))

            stats = await db.fetch_one('SELECT * FROM marketplace_seller_stats WHERE user_id = $1', user['id'])

            if not stats or stats['total_sales'] == 0:
                await ctx.send(f"📭 {target.display_name} hasn't made any sales yet.")
                return

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

            if reviews:
                reviews_text = ''
                for review in reviews:
                    reviewer = ctx.guild.get_member(int(review['reviewer_discord_id']))
                    name = reviewer.display_name if reviewer else 'Unknown'
                    stars = '⭐' * review['rating']
                    comment_text = (
                        review['comment'][:50] + '...'
                        if review['comment'] and len(review['comment']) > 50
                        else (review['comment'] or 'No comment')
                    )
                    reviews_text += f'{stars} **{name}**: {comment_text}\n'
                embed.add_field(name='📝 Recent Reviews', value=reviews_text, inline=False)

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
        """View reviews you have received"""
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

            from datetime import datetime, timedelta

            if listing['bumped_at'] and listing['bumped_at'] > datetime.utcnow() - timedelta(hours=24):
                time_left = listing['bumped_at'] + timedelta(hours=24) - datetime.utcnow()
                hours = int(time_left.total_seconds() // 3600)
                await ctx.send(f'⏱️ You can bump this listing again in {hours} hours.')
                return

            await db.execute('UPDATE marketplace_listings SET bumped_at = NOW() WHERE id = $1', listing_id)

            embed = await success_embed(
                title='Listing Bumped',
                description=(
                    f'**{listing["title"]}** has been bumped to the top!\n\n'
                    'Also bump with our partner bots to reach even more people:\n'
                    f'\u2022 <@302050872383242240> — Discord Bump Bot\n'
                    f'\u2022 <@1222548162741538938> — Discadia Bot'
                ),
                contributor_source=__name__,
                user=ctx.author,
            )
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f'Bump error: {str(e)}')
            await ctx.send('❌ An error occurred.')

    # ==================== SHARED LOGIC ====================

    async def _update_seller_stats(self, user_id: int):
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


def setup(bot):
    bot.add_cog(MarketplaceReviews(bot))
