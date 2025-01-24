const mongoose = require('mongoose');

const dashboardConfigSchema = new mongoose.Schema({
    guildId: { type: String, required: true },
    channelId: { type: String, required: true },
    messageIds: {
        overall: String,
        gaming: String,
        voice: String,
        text: String,
        github: String,
        welcome: String
    }
});

module.exports = mongoose.model('DashboardConfig', dashboardConfigSchema); 