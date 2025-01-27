const { PriceTracker } = require('../utils/priceTracker');
const TrackedProduct = require('../models/TrackedProduct');
const { logger } = require('../utils/logger');

class PopularProductTracker {
    static categories = {
        electronics: [
            'https://www.amazon.in/dp/B0BDHX8Z63',  // Example PS5
            'https://www.amazon.in/dp/B09G9HD6PD',  // Example iPhone
            // Add more popular product URLs
        ],
        gaming: [
            'https://www.amazon.in/dp/B0BT9CXXXX',  // Example Gaming Mouse
            // Add more gaming products
        ]
    };

    static async trackPopularProducts() {
        try {
            for (const [category, urls] of Object.entries(this.categories)) {
                for (const url of urls) {
                    const product = await PriceTracker.trackProduct(url);
                    await TrackedProduct.findOneAndUpdate(
                        { url },
                        {
                            ...product,
                            currentPrice: product.price,
                            $push: { priceHistory: { price: product.price } },
                            category,
                            isPopular: true
                        },
                        { upsert: true }
                    );
                }
            }
        } catch (error) {
            logger.error('Error tracking popular products:', error);
        }
    }
}

module.exports = PopularProductTracker; 