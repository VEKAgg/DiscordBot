const { EmbedBuilder } = require('discord.js');
const axios = require('axios');
const cheerio = require('cheerio');
const { logger } = require('../utils/logger');
const TrackedProduct = require('../models/TrackedProduct');
const { PriceTracker } = require('../utils/priceTracker');

class DealTracker {
    constructor(client) {
        this.client = client;
        this.dealChannels = new Map();
        this.platforms = {
            amazonIn: this.checkAmazonInDeals,
            amazonAe: this.checkAmazonAeDeals,
            flipkart: this.checkFlipkartDeals,
            noon: this.checkNoonDeals,
            epic: this.checkEpicGames,
            steam: this.checkSteamDeals
        };
        this.lastChecked = new Map();
    }

    async init() {
        // Check deals every 30 minutes
        setInterval(() => this.checkAllDeals(), 1800000);
        // Check free games every 6 hours
        setInterval(() => this.checkFreeGames(), 21600000);
    }

    async checkFreeGames() {
        try {
            const epicGames = await this.getEpicFreeGames();
            const steamGames = await this.getSteamFreeGames();
            
            for (const [channelId, settings] of this.dealChannels) {
                if (settings.freeGames) {
                    const channel = await this.client.channels.fetch(channelId);
                    if (channel) {
                        for (const game of [...epicGames, ...steamGames]) {
                            const embed = new EmbedBuilder()
                                .setTitle('🎮 Free Game Alert!')
                                .setDescription(`**${game.title}** is currently FREE!`)
                                .addFields([
                                    { name: 'Platform', value: game.platform, inline: true },
                                    { name: 'End Date', value: game.endDate || 'Unknown', inline: true }
                                ])
                                .setURL(game.url)
                                .setColor('#00ff00')
                                .setTimestamp();

                            if (game.image) embed.setImage(game.image);
                            await channel.send({ embeds: [embed] });
                        }
                    }
                }
            }
        } catch (error) {
            logger.error('Error checking free games:', error);
        }
    }

    async getEpicFreeGames() {
        try {
            const response = await axios.get('https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions');
            const games = response.data.data.Catalog.searchStore.elements
                .filter(game => game.promotions && game.promotions.promotionalOffers.length > 0)
                .map(game => ({
                    title: game.title,
                    url: `https://store.epicgames.com/en-US/p/${game.urlSlug}`,
                    platform: 'Epic Games',
                    image: game.keyImages[0]?.url,
                    endDate: new Date(game.promotions.promotionalOffers[0].promotionalOffers[0].endDate)
                        .toLocaleDateString()
                }));
            return games;
        } catch (error) {
            logger.error('Error fetching Epic Games:', error);
            return [];
        }
    }

    async notifyDeals(deals, channelId) {
        const channel = await this.client.channels.fetch(channelId);
        if (!channel) return;

        for (const deal of deals) {
            const embed = new EmbedBuilder()
                .setTitle(`🎮 New Deal on ${deal.platform}!`)
                .setDescription(`**${deal.title}**`)
                .addFields([
                    { name: 'Original Price', value: `$${deal.originalPrice}`, inline: true },
                    { name: 'Sale Price', value: `$${deal.salePrice}`, inline: true },
                    { name: 'Discount', value: `${deal.discount}%`, inline: true }
                ])
                .setURL(deal.url)
                .setImage(deal.thumbnail)
                .setColor('#00ff00')
                .setTimestamp();

            await channel.send({ embeds: [embed] });
        }
    }

    // Implement platform-specific deal checking methods
    async checkSteamDeals() {
        // Steam API implementation
    }

    async checkEpicGames() {
        // Epic Games Store API implementation
    }

    async checkAmazonInDeals() {
        // Amazon price tracking implementation
    }

    async checkAmazonAeDeals() {
        // Amazon price tracking implementation
    }

    async checkFlipkartDeals() {
        // Flipkart price tracking implementation
    }

    async checkNoonDeals() {
        // Noon price tracking implementation
    }

    async checkTrackedProducts() {
        try {
            const products = await TrackedProduct.find({
                lastChecked: { $lte: new Date(Date.now() - 1800000) } // Check products not updated in last 30 mins
            });

            for (const product of products) {
                const currentData = await PriceTracker.trackProduct(product.url);
                
                if (currentData.price !== product.currentPrice) {
                    // Price changed, notify watchers
                    for (const watcher of product.watchers) {
                        if (watcher.notifyOnAnyChange || 
                            (watcher.targetPrice && currentData.price <= watcher.targetPrice)) {
                            const user = await this.client.users.fetch(watcher.userId);
                            if (user) {
                                const embed = this.createPriceAlertEmbed(product, currentData);
                                await user.send({ embeds: [embed] });
                            }
                        }
                    }

                    // Update product in database
                    product.priceHistory.push({ price: currentData.price });
                    product.currentPrice = currentData.price;
                }
                
                product.lastChecked = new Date();
                await product.save();
            }
        } catch (error) {
            logger.error('Error checking tracked products:', error);
        }
    }
}

module.exports = DealTracker; 