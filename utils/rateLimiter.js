const NodeCache = require('node-cache');

class RateLimiter {
    constructor() {
        this.cache = new NodeCache();
        this.limits = {
            'news': { calls: 90, period: 86400 },    // 90 calls per day (NewsAPI)
            'weather': { calls: 54, period: 60 },     // 54 calls per minute (OpenWeather)
            'crypto': { calls: 9000, period: 2592000 }, // 9000 calls per month (CoinMarketCap)
            'stock': { calls: 4, period: 60 },        // 4 calls per minute (AlphaVantage)
            'cat': { calls: 9, period: 60 },          // 9 calls per minute (Cat API)
            'dog': { calls: 45, period: 60 },         // 45 calls per minute (Dog API)
            'joke': { calls: 45, period: 60 },        // 45 calls per minute (JokeAPI)
            'github': { calls: 4500, period: 3600 }   // 4500 calls per hour (GitHub)
        };
    }

    async checkLimit(apiName) {
        const key = `${apiName}_calls`;
        const timeKey = `${apiName}_reset`;
        const limit = this.limits[apiName];

        if (!limit) return { success: true };

        const currentCalls = this.cache.get(key) || 0;
        const resetTime = this.cache.get(timeKey) || Date.now();

        if (Date.now() >= resetTime) {
            this.cache.set(key, 1);
            this.cache.set(timeKey, Date.now() + (limit.period * 1000));
            return { 
                success: true,
                remaining: limit.calls - 1,
                resetIn: limit.period
            };
        }

        if (currentCalls >= limit.calls) {
            const resetInSeconds = Math.ceil((resetTime - Date.now()) / 1000);
            return {
                success: false,
                resetIn: resetInSeconds,
                message: `Rate limit exceeded. Try again in ${Math.ceil(resetInSeconds / 60)} minutes.`
            };
        }

        this.cache.set(key, currentCalls + 1);
        return {
            success: true,
            remaining: limit.calls - currentCalls - 1,
            resetIn: Math.ceil((resetTime - Date.now()) / 1000)
        };
    }
}

module.exports = new RateLimiter(); 