const axios = require('axios');
const cheerio = require('cheerio');
const { logger } = require('./logger');

class PriceTracker {
    static supportedPlatforms = {
        'amazon.in': {
            priceSelector: '#priceblock_ourprice, #priceblock_dealprice, .a-price-whole',
            titleSelector: '#productTitle',
            imageSelector: '#landingImage'
        },
        'amazon.ae': {
            priceSelector: '#priceblock_ourprice, #priceblock_dealprice, .a-price-whole',
            titleSelector: '#productTitle',
            imageSelector: '#landingImage'
        },
        'flipkart.com': {
            priceSelector: '._30jeq3',
            titleSelector: '.B_NuCI',
            imageSelector: '._396cs4'
        },
        'noon.com': {
            priceSelector: '.priceNow',
            titleSelector: '.productTitle',
            imageSelector: '.productImage'
        }
    };

    static async trackProduct(url) {
        try {
            const platform = this.getPlatform(url);
            if (!this.supportedPlatforms[platform]) {
                throw new Error('Unsupported platform');
            }

            const response = await axios.get(url, {
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            });

            const $ = cheerio.load(response.data);
            const selectors = this.supportedPlatforms[platform];

            const price = this.extractPrice($, selectors.priceSelector);
            const title = $(selectors.titleSelector).text().trim();
            const image = $(selectors.imageSelector).attr('src');

            return {
                url,
                platform,
                title,
                price,
                image,
                lastChecked: new Date(),
                isAvailable: price !== null
            };
        } catch (error) {
            logger.error(`Error tracking product (${url}):`, error);
            return {
                url,
                platform: this.getPlatform(url),
                error: error.message,
                lastChecked: new Date(),
                isAvailable: false
            };
        }
    }

    static getPlatform(url) {
        try {
            const hostname = new URL(url).hostname;
            return hostname.replace('www.', '');
        } catch {
            throw new Error('Invalid URL');
        }
    }

    static extractPrice($, selector) {
        const priceText = $(selector).first().text().trim();
        const numericPrice = priceText.replace(/[^0-9.]/g, '');
        return numericPrice ? parseFloat(numericPrice) : null;
    }

    static async trackMultipleProducts(urls) {
        const results = await Promise.allSettled(
            urls.map(url => this.trackProduct(url))
        );

        return results.map(result => {
            if (result.status === 'fulfilled') {
                return result.value;
            }
            return {
                url: urls[results.indexOf(result)],
                error: result.reason.message,
                lastChecked: new Date(),
                isAvailable: false
            };
        });
    }
}

module.exports = PriceTracker; 