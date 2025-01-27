const mongoose = require('mongoose');

const analyticsConfigSchema = new mongoose.Schema({
    guildId: { type: String, required: true, unique: true },
    enabled: { type: Boolean, default: false },
    trackingChannels: [String],
    excludedChannels: [String],
    lastReset: { type: Date, default: Date.now }
});

module.exports = mongoose.model('AnalyticsConfig', analyticsConfigSchema); 