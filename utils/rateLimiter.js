const NodeCache = require('node-cache');
const cache = new NodeCache();

const limits = {
    quote: { max: 5, window: 60 },    // 5 requests per minute
    fact: { max: 5, window: 60 },     // 5 requests per minute
    animal: { max: 5, window: 60 },   // 5 requests per minute
    github: { max: 30, window: 3600 }, // 30 requests per hour
    default: { max: 10, window: 60 }  // Default: 10 requests per minute
};

async function checkLimit(command) {
    const userId = 'global'; // For now, using global limits
    const key = `${command}_${userId}`;
    const limit = limits[command] || limits.default;
    
    let usage = cache.get(key) || { count: 0, resetTime: Date.now() + (limit.window * 1000) };
    
    if (Date.now() > usage.resetTime) {
        usage = { count: 0, resetTime: Date.now() + (limit.window * 1000) };
    }
    
    if (usage.count >= limit.max) {
        const resetIn = Math.ceil((usage.resetTime - Date.now()) / 1000);
        return {
            success: false,
            message: `Rate limit exceeded. Please try again in ${resetIn} seconds.`,
            resetIn
        };
    }
    
    usage.count++;
    cache.set(key, usage);
    
    return { success: true, resetIn: usage.resetTime - Date.now() };
}

module.exports = { checkLimit }; 