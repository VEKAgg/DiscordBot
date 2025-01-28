const axios = require('axios');
const cheerio = require('cheerio');
const { logger } = require('./logger');

class PriceTracker {
    static async trackProduct(url) {
        const platform = this.detectPlatform(url);
        switch (platform) {
            case 'amazon.in':
                return await this.trackAmazonIn(url);
            case 'amazon.ae':
                return await this.trackAmazonAe(url);
            case 'flipkart':
                return await this.trackFlipkart(url);
            case 'noon':
                return await this.trackNoon(url);
            default:
                throw new Error('Unsupported platform');
        }
    }

    static detectPlatform(url) {
        if (url.includes('amazon.in')) return 'amazon.in';
        if (url.includes('amazon.ae')) return 'amazon.ae';
        if (url.includes('flipkart.com')) return 'flipkart';
        if (url.includes('noon.com')) return 'noon';
        return null;
    }

    static async trackAmazonIn(url) {
        try {
            const response = await axios.get(url, {
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            });
            const $ = cheerio.load(response.data);
            const price = $('.a-price-whole').first().text().replace(/[,.]/g, '');
            const title = $('#productTitle').text().trim();
            
            return {
                title,
                price: parseInt(price),
                url,
                platform: 'Amazon India'
            };
        } catch (error) {
            logger.error('Error tracking Amazon.in product:', error);
            throw error;
        }
    }

    // Add similar methods for other platforms...
}

module.exports = PriceTracker; 