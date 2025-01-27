const mongoose = require('mongoose');

const notificationConfigSchema = new mongoose.Schema({
    guildId: {
        type: String,
        required: true,
        unique: true,
        index: true
    },
    channels: {
        announcements: String,
        updates: String,
        alerts: String
    },
    roles: {
        notificationSquad: String,
        updatePing: String,
        eventPing: String
    },
    settings: {
        mentionRoles: {
            type: Boolean,
            default: true
        },
        cooldown: {
            type: Number,
            default: 300000 // 5 minutes
        },
        blacklistedChannels: [String]
    }
}, {
    timestamps: true
});

module.exports = mongoose.model('NotificationConfig', notificationConfigSchema);
