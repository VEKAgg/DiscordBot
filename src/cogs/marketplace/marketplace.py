import datetime
import logging

import nextcord
from nextcord.ext import commands

from src.database.database import db
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import safe_send, safe_slash_command

logger = logging.getLogger('VEKA.marketplace')


class Marketplace(commands.Cog):
    @nextcord.slash_command(name='marketplace', description='Buy and sell items within the community')
    async def marketplace(self, interaction: nextcord.Interaction):
        pass

    def __init__(self, bot):
        self.bot = bot

    @marketplace.subcommand(name='post', description='Create a new marketplace listing')
    @safe_slash_command(requires_db=True)
    async def mp_post(
        self,
        interaction: nextcord.Interaction,
        title: str,
        price: float,
        category: str = nextcord.SlashOption(
            name='category',
            description='Category of the item',
            choices={'Hardware': 'Hardware', 'Software': 'Software', 'Services': 'Services', 'Other': 'Other'},
        ),
        condition: str = nextcord.SlashOption(
            name='condition',
            description='Condition of the item',
            choices={'New': 'new', 'Like New': 'like_new', 'Good': 'good', 'Fair': 'fair', 'Poor': 'poor'},
        ),
        description: str = '',
        image_url: str = '',
    ):
        """Create a new listing in the marketplace."""
        if price < 0:
            embed = await error_embed(
                'Invalid Price', 'Price cannot be negative.', user=interaction.user, contributor_source=__name__
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        if len(title) < 3 or len(title) > 100:
            embed = await error_embed(
                'Invalid Title',
                'Title must be between 3 and 100 characters.',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        # Fetch category ID based on the provided name
        category_record = await db.fetch_one('SELECT id FROM marketplace_categories WHERE name = $1', category)
        if not category_record:
            # Fallback: insert with SERIAL auto-generated id, then re-fetch
            await db.execute(
                "INSERT INTO marketplace_categories (name, emoji, is_active) VALUES ($1, '📦', TRUE) ON CONFLICT DO NOTHING",
                category,
            )
            category_record = await db.fetch_one('SELECT id FROM marketplace_categories WHERE name = $1', category)
            if not category_record:
                embed = await error_embed(
                    'Category Error', 'Could not find or create the category.', contributor_source=__name__
                )
                await safe_send(interaction, embed=embed, ephemeral=True)
                return

        category_id = category_record['id']

        listing_id = f'MP{int(datetime.datetime.utcnow().timestamp())}'

        # Ensure user exists in db
        await db.execute('INSERT INTO users (discord_id) VALUES ($1) ON CONFLICT DO NOTHING', str(interaction.user.id))
        user = await db.fetch_one('SELECT id FROM users WHERE discord_id = $1', str(interaction.user.id))
        if user is None:
            embed = await error_embed(
                'User Error',
                'Could not find or create your user record.',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        await db.execute(
            """INSERT INTO marketplace_listings
               (id, seller_id, title, description, price, category_id, condition, status, image_url)
               VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', $8)""",
            listing_id,
            user['id'],
            title,
            description,
            price,
            category_id,
            condition,
            image_url or None,
        )

        embed = await success_embed(
            title='Listing Created',
            description=f'Your item **{title}** has been posted for **${price:.2f}**.',
            user=interaction.user,
            contributor_source=__name__,
        )
        embed.add_field(name='Listing ID', value=f'`{listing_id}`', inline=True)
        await safe_send(interaction, embed=embed, ephemeral=False)

    @marketplace.subcommand(name='browse', description='Browse active marketplace listings')
    @safe_slash_command(requires_db=True)
    async def mp_browse(
        self,
        interaction: nextcord.Interaction,
        category: str = nextcord.SlashOption(
            name='category',
            description='Filter by category',
            required=False,
            choices={'Hardware': 'Hardware', 'Software': 'Software', 'Services': 'Services', 'Other': 'Other'},
        ),
    ):
        """Browse listings."""
        query = """
            SELECT l.id, l.title, l.price, l.condition, c.name as cat_name, c.emoji, u.discord_id
            FROM marketplace_listings l
            JOIN users u ON l.seller_id = u.id
            JOIN marketplace_categories c ON l.category_id = c.id
            WHERE l.status = 'active'
        """
        args = []
        if category:
            query += ' AND c.name = $1'
            args.append(category)

        query += ' ORDER BY l.created_at DESC LIMIT 10'
        listings = await db.fetch_many(query, *args)

        if not listings:
            embed = await info_embed(
                'No Listings Found',
                'There are no active listings that match your criteria.',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        embed = await info_embed(
            title='Marketplace Listings',
            description='Use `/marketplace view <id>` for more details on an item.',
            user=interaction.user,
            contributor_source=__name__,
        )

        for listing in listings:
            seller_mention = f'<@{listing["discord_id"]}>'
            cond_str = str(listing['condition']).replace('_', ' ').title()
            val = f'💰 **${listing["price"]:.2f}** | 📦 {cond_str} | 👤 {seller_mention}\n🆔 `{listing["id"]}`'
            embed.add_field(name=f'{listing["emoji"] or "📦"} {listing["title"]}', value=val, inline=False)

        await safe_send(interaction, embed=embed, ephemeral=False)

    @marketplace.subcommand(name='view', description='View details of a specific listing')
    @safe_slash_command(requires_db=True)
    async def mp_view(self, interaction: nextcord.Interaction, listing_id: str):
        """View a listing."""
        await db.execute('UPDATE marketplace_listings SET views = views + 1 WHERE id = $1', listing_id)

        listing = await db.fetch_one(
            """SELECT l.*, c.name as cat_name, c.emoji, u.discord_id
               FROM marketplace_listings l
               JOIN users u ON l.seller_id = u.id
               JOIN marketplace_categories c ON l.category_id = c.id
               WHERE l.id = $1""",
            listing_id,
        )

        if not listing:
            embed = await error_embed(
                'Not Found', 'The listing could not be found.', user=interaction.user, contributor_source=__name__
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        seller = self.bot.get_user(int(listing['discord_id']))
        embed = await info_embed(
            title=f'{listing["emoji"] or "📦"} {listing["title"]}',
            description=listing['description'] or 'No description provided.',
            user=interaction.user,
            contributor_source=__name__,
        )
        embed.add_field(name='Price', value=f'${listing["price"]:.2f}', inline=True)
        embed.add_field(name='Condition', value=str(listing['condition']).replace('_', ' ').title(), inline=True)
        embed.add_field(name='Category', value=listing['cat_name'], inline=True)
        embed.add_field(name='Seller', value=seller.mention if seller else f'<@{listing["discord_id"]}>', inline=True)
        embed.add_field(name='Status', value=str(listing['status']).title(), inline=True)
        embed.add_field(name='Views', value=str(listing['views']), inline=True)

        if listing['image_url']:
            embed.set_image(url=listing['image_url'])

        await safe_send(interaction, embed=embed, ephemeral=False)

    @marketplace.subcommand(name='mylistings', description='View your own listings')
    @safe_slash_command(requires_db=True)
    async def mp_mylistings(self, interaction: nextcord.Interaction):
        """View your listings."""
        listings = await db.fetch_many(
            """SELECT l.id, l.title, l.price, l.status, l.views
               FROM marketplace_listings l
               JOIN users u ON l.seller_id = u.id
               WHERE u.discord_id = $1
               ORDER BY l.created_at DESC LIMIT 10""",
            str(interaction.user.id),
        )

        if not listings:
            embed = await info_embed(
                'No Listings',
                "You don't have any marketplace listings.",
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        embed = await info_embed(
            'Your Listings',
            'Here are your recent marketplace listings.',
            user=interaction.user,
            contributor_source=__name__,
        )
        for listing in listings:
            embed.add_field(
                name=listing['title'],
                value=f'💰 ${listing["price"]:.2f} | Status: {str(listing["status"]).title()} | Views: {listing["views"]}\n🆔 `{listing["id"]}`',
                inline=False,
            )

        await safe_send(interaction, embed=embed, ephemeral=True)

    @marketplace.subcommand(name='withdraw', description='Withdraw one of your active listings')
    @safe_slash_command(requires_db=True)
    async def mp_withdraw(self, interaction: nextcord.Interaction, listing_id: str):
        """Withdraw a listing."""
        listing = await db.fetch_one(
            """SELECT l.id, l.status, u.discord_id
               FROM marketplace_listings l
               JOIN users u ON l.seller_id = u.id
               WHERE l.id = $1""",
            listing_id,
        )

        if not listing:
            embed = await error_embed(
                'Not Found', 'The listing could not be found.', user=interaction.user, contributor_source=__name__
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        if listing['discord_id'] != str(interaction.user.id):
            embed = await error_embed(
                'Permission Denied',
                'You can only withdraw your own listings.',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        if listing['status'] != 'active':
            embed = await error_embed(
                'Invalid Action',
                'Only active listings can be withdrawn.',
                user=interaction.user,
                contributor_source=__name__,
            )
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        await db.execute("UPDATE marketplace_listings SET status = 'withdrawn' WHERE id = $1", listing_id)

        embed = await success_embed(
            'Listing Withdrawn',
            f'Listing `{listing_id}` has been withdrawn successfully.',
            user=interaction.user,
            contributor_source=__name__,
        )
        await safe_send(interaction, embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(Marketplace(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.marketplace.marketplace')
