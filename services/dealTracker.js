const { EmbedBuilder } = require('discord.js');
const axios = require('axios');
const cheerio = require('cheerio');
const { logger } = require('../utils/logger');
const TrackedProduct = require('../models/TrackedProduct');
const { PriceTracker } = require('../utils/priceTracker');
const Deal = require('../models/Deal');

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

    async checkSteamDeals() {
        try {
            const response = await axios.get('https://store.steampowered.com/api/featuredcategories', {
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            });

            const specials = response.data.specials.items;
            const processedDeals = [];

            for (const item of specials) {
                const discount = Math.round(((item.original_price - item.final_price) / item.original_price) * 100);
                
                if (discount >= 50) { // Only track major Steam deals
                    processedDeals.push({
                        platform: 'Steam',
                        title: item.name,
                        originalPrice: item.original_price / 100, // Steam prices are in cents
                        salePrice: item.final_price / 100,
                        discount,
                        url: `https://store.steampowered.com/app/${item.id}`,
                        thumbnail: item.large_capsule_image,
                        expiryDate: new Date(Date.now() + (item.discount_expiration * 1000)),
                        postedDate: new Date()
                    });
                }
            }

            return processedDeals;
        } catch (error) {
            logger.error('Error checking Steam deals:', error);
            return [];
        }
    }

    async checkEpicGames() {
        try {
            const response = await axios.get('https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions');
            const games = response.data.data.Catalog.searchStore.elements;
            const processedDeals = [];

            for (const game of games) {
                if (!game.price || !game.price.totalPrice) continue;

                const originalPrice = game.price.totalPrice.originalPrice / 100;
                const salePrice = game.price.totalPrice.discountPrice / 100;
                
                if (originalPrice === 0 || salePrice === originalPrice) continue;

                const discount = Math.round(((originalPrice - salePrice) / originalPrice) * 100);

                if (discount >= 30) { // Only track significant Epic deals
                    processedDeals.push({
                        platform: 'Epic Games',
                        title: game.title,
                        originalPrice,
                        salePrice,
                        discount,
                        url: `https://store.epicgames.com/en-US/p/${game.urlSlug}`,
                        thumbnail: game.keyImages.find(img => img.type === 'OfferImageWide')?.url,
                        expiryDate: new Date(game.price.lineOffers[0]?.endDate || Date.now() + (24 * 60 * 60 * 1000)),
                        postedDate: new Date()
                    });
                }
            }

            return processedDeals;
        } catch (error) {
            logger.error('Error checking Epic Games deals:', error);
            return [];
        }
    }

    async checkAmazonInDeals() {
        try {
            const deals = await axios.get('https://www.amazon.in/deals', {
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            });

            const $ = cheerio.load(deals.data);
            const dealItems = $('.dealContainer');
            const processedDeals = [];

            for (const item of dealItems) {
                const $item = $(item);
                const url = 'https://www.amazon.in' + $item.find('a').attr('href');
                
                // Use our PriceTracker to get accurate product details
                const product = await PriceTracker.trackProduct(url);
                
                if (!product || !product.price) continue;

                const originalPrice = parseFloat($item.find('.dealPriceText').text().replace(/[^0-9.]/g, ''));
                const discount = Math.round(((originalPrice - product.price) / originalPrice) * 100);

                if (discount >= 20) { // Only track significant deals
                    processedDeals.push({
                        platform: 'Amazon India',
                        title: product.title,
                        originalPrice,
                        salePrice: product.price,
                        discount,
                        url,
                        thumbnail: product.image,
                        expiryDate: new Date(Date.now() + 24 * 60 * 60 * 1000), // 24 hours from now
                        postedDate: new Date()
                    });
                }
            }

            return processedDeals;
        } catch (error) {
            logger.error('Error checking Amazon India deals:', error);
            return [];
        }
    }

    async checkAmazonAeDeals() {
        // Amazon price tracking implementation
    }

    async checkFlipkartDeals() {
        try {
            const deals = await axios.get('https://www.flipkart.com/offers-store', {
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            });

            const $ = cheerio.load(deals.data);
            const dealItems = $('._2kHMtA');
            const processedDeals = [];

            for (const item of dealItems) {
                const $item = $(item);
                const url = 'https://www.flipkart.com' + $item.find('a').attr('href');
                
                const product = await PriceTracker.trackProduct(url);
                
                if (!product || !product.price) continue;

                const originalPrice = parseFloat($item.find('._3I9_wc').text().replace(/[^0-9.]/g, ''));
                const discount = Math.round(((originalPrice - product.price) / originalPrice) * 100);

                if (discount >= 20) {
                    processedDeals.push({
                        platform: 'Flipkart',
                        title: product.title,
                        originalPrice,
                        salePrice: product.price,
                        discount,
                        url,
                        thumbnail: product.image,
                        expiryDate: new Date(Date.now() + 24 * 60 * 60 * 1000),
                        postedDate: new Date()
                    });
                }
            }

            return processedDeals;
        } catch (error) {
            logger.error('Error checking Flipkart deals:', error);
            return [];
        }
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

    async checkAllDeals() {
        try {
            for (const [platform, checkFunction] of Object.entries(this.platforms)) {
                if (Date.now() - (this.lastChecked.get(platform) || 0) < 1800000) continue; // Skip if checked within 30 mins

                const deals = await checkFunction.call(this);
                
                // Store deals in database
                for (const deal of deals) {
                    await Deal.findOneAndUpdate(
                        { url: deal.url },
                        { ...deal },
                        { upsert: true }
                    );
                }

                // Notify channels
                for (const [channelId, settings] of this.dealChannels) {
                    if (settings[platform]) {
                        await this.notifyDeals(deals, channelId);
                    }
                }

                this.lastChecked.set(platform, Date.now());
            }
        } catch (error) {
            logger.error('Error in checkAllDeals:', error);
        }
    }
}

module.exports = DealTracker; 