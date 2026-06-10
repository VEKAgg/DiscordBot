import datetime
import logging
from typing import Optional

import nextcord
from nextcord.ext import commands

from src.database.database import db
from src.utils.embeds import error_embed, info_embed, success_embed
from src.utils.safety import safe_slash_command, safe_send

logger = logging.getLogger('VEKA.marketplace')


class Marketplace(commands.Cog):
    marketplace = nextcord.SlashCommandGroup('marketplace', 'Buy and sell items within the community')

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
            embed = error_embed('Invalid Price', 'Price cannot be negative.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        if len(title) < 3 or len(title) > 100:
            embed = error_embed('Invalid Title', 'Title must be between 3 and 100 characters.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        # Fetch category ID based on the provided name
        category_record = await db.fetch_one(
            "SELECT id FROM marketplace_categories WHERE name = $1 LIMIT 1", category
        )
        if not category_record:
            # Fallback to inserting category if it doesn't exist to ensure robustness
            cat_id = f"CAT_{category.upper()}"
            await db.execute(
                "INSERT INTO marketplace_categories (id, name, emoji, is_active) VALUES ($1, $2, '📦', TRUE) ON CONFLICT DO NOTHING",
                cat_id, category
            )
            category_id = cat_id
        else:
            category_id = category_record['id']

        listing_id = f"MP{int(datetime.datetime.utcnow().timestamp())}"
        
        # Ensure user exists in db
        await db.execute("INSERT INTO users (discord_id) VALUES ($1) ON CONFLICT DO NOTHING", str(interaction.user.id))
        user = await db.fetch_one("SELECT id FROM users WHERE discord_id = $1", str(interaction.user.id))

        await db.execute(
            """INSERT INTO marketplace_listings 
               (id, seller_id, title, description, price, category_id, condition, status, image_url)
               VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', $8)""",
            listing_id, user['id'], title, description, price, category_id, condition, image_url or None
        )

        embed = success_embed(
            title="Listing Created",
            description=f"Your item **{title}** has been posted for **${price:.2f}**.",
            contributor_source=__name__
        )
        embed.add_field(name="Listing ID", value=f"`{listing_id}`", inline=True)
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
            query += " AND c.name = $1"
            args.append(category)
            
        query += " ORDER BY l.created_at DESC LIMIT 10"
        listings = await db.fetch_many(query, *args)

        if not listings:
            embed = info_embed('No Listings Found', 'There are no active listings that match your criteria.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        embed = info_embed(
            title="Marketplace Listings",
            description="Use `/marketplace view <id>` for more details on an item.",
            contributor_source=__name__
        )

        for listing in listings:
            seller_mention = f"<@{listing['discord_id']}>"
            cond_str = str(listing['condition']).replace('_', ' ').title()
            val = f"💰 **${listing['price']:.2f}** | 📦 {cond_str} | 👤 {seller_mention}\n🆔 `{listing['id']}`"
            embed.add_field(name=f"{listing['emoji'] or '📦'} {listing['title']}", value=val, inline=False)

        await safe_send(interaction, embed=embed, ephemeral=False)

    @marketplace.subcommand(name='view', description='View details of a specific listing')
    @safe_slash_command(requires_db=True)
    async def mp_view(self, interaction: nextcord.Interaction, listing_id: str):
        """View a listing."""
        await db.execute("UPDATE marketplace_listings SET views = views + 1 WHERE id = $1", listing_id)
        
        listing = await db.fetch_one(
            """SELECT l.*, c.name as cat_name, c.emoji, u.discord_id
               FROM marketplace_listings l
               JOIN users u ON l.seller_id = u.id
               JOIN marketplace_categories c ON l.category_id = c.id
               WHERE l.id = $1""",
            listing_id
        )

        if not listing:
            embed = error_embed('Not Found', 'The listing could not be found.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        seller = self.bot.get_user(int(listing['discord_id']))
        embed = info_embed(title=f"{listing['emoji'] or '📦'} {listing['title']}", description=listing['description'] or "No description provided.", contributor_source=__name__)
        embed.add_field(name="Price", value=f"${listing['price']:.2f}", inline=True)
        embed.add_field(name="Condition", value=str(listing['condition']).replace('_', ' ').title(), inline=True)
        embed.add_field(name="Category", value=listing['cat_name'], inline=True)
        embed.add_field(name="Seller", value=seller.mention if seller else f"<@{listing['discord_id']}>", inline=True)
        embed.add_field(name="Status", value=str(listing['status']).title(), inline=True)
        embed.add_field(name="Views", value=str(listing['views']), inline=True)

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
            str(interaction.user.id)
        )

        if not listings:
            embed = info_embed('No Listings', "You don't have any marketplace listings.", contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        embed = info_embed('Your Listings', "Here are your recent marketplace listings.", contributor_source=__name__)
        for l in listings:
            embed.add_field(
                name=l['title'],
                value=f"💰 ${l['price']:.2f} | Status: {str(l['status']).title()} | Views: {l['views']}\n🆔 `{l['id']}`",
                inline=False
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
            listing_id
        )

        if not listing:
            embed = error_embed('Not Found', 'The listing could not be found.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        if listing['discord_id'] != str(interaction.user.id):
            embed = error_embed('Permission Denied', 'You can only withdraw your own listings.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        if listing['status'] != 'active':
            embed = error_embed('Invalid Action', 'Only active listings can be withdrawn.', contributor_source=__name__)
            await safe_send(interaction, embed=embed, ephemeral=True)
            return

        await db.execute("UPDATE marketplace_listings SET status = 'withdrawn' WHERE id = $1", listing_id)
        
        embed = success_embed('Listing Withdrawn', f"Listing `{listing_id}` has been withdrawn successfully.", contributor_source=__name__)
        await safe_send(interaction, embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(Marketplace(bot))
    logging.getLogger('VEKA').info('Loaded cog: src.cogs.marketplace.marketplace')
