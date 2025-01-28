const mongoose = require('mongoose');

const trackedProductSchema = new mongoose.Schema({
    url: { type: String, required: true, unique: true },
    title: { type: String, required: true },
    platform: { type: String, required: true },
    currentPrice: { type: Number, required: true },
    priceHistory: [{
        price: Number,
        date: { type: Date, default: Date.now }
    }],
    category: { type: String, required: true },
    isPopular: { type: Boolean, default: false },
    watchers: [{
        userId: String,
        notifyOnAnyChange: { type: Boolean, default: false },
        targetPrice: Number
    }],
    lastChecked: { type: Date, default: Date.now }
});

module.exports = mongoose.model('TrackedProduct', trackedProductSchema); 