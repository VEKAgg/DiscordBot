const mongoose = require('mongoose');

const analyticsConfigSchema = new mongoose.Schema({
    guildId: { type: String, required: true },
    features: {
        welcome: { enabled: Boolean, channelId: String },
        invite: { enabled: Boolean, channelId: String },
        command: { enabled: Boolean, channelId: String },
        connection: { enabled: Boolean, channelId: String }
    },
    reporting: {
        interval: { type: String, default: 'daily' },
        channelId: String
    }
});

module.exports = mongoose.model('AnalyticsConfig', analyticsConfigSchema); 