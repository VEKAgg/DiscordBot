const mongoose = require('mongoose');

const dashboardConfigSchema = new mongoose.Schema({
    guildId: { type: String, required: true, unique: true },
    channelId: { type: String, required: true },
    messageIds: {
        overall: String,
        gaming: String,
        voice: String,
        text: String,
        github: String,
        welcome: String
    },
    lastUpdate: { type: Date, default: Date.now }
});

module.exports = mongoose.model('DashboardConfig', dashboardConfigSchema); 