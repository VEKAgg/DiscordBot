const mongoose = require('mongoose');
const { Schema } = mongoose;
const DashboardConfig = require('../models/DashboardConfig');
const AnalyticsConfig = require('../models/AnalyticsConfig');
const GamingConfig = require('../models/GamingConfig');
const User = require('../models/User');

const userSchema = new Schema({
    userId: { type: String, required: true },
    guildId: { type: String, required: true },
    xp: { type: Number, default: 0 },
    level: { type: Number, default: 0 },
    messages: {
        total: { type: Number, default: 0 },
        daily: { type: Number, default: 0 },
        weekly: { type: Number, default: 0 },
        monthly: { type: Number, default: 0 },
        lastMessageDate: { type: Date }
    },
    voiceTime: {
        total: { type: Number, default: 0 },
        daily: { type: Number, default: 0 },
        weekly: { type: Number, default: 0 },
        monthly: { type: Number, default: 0 },
        lastVoiceDate: { type: Date }
    },
    lastVoiceJoinDate: { type: Date }
});

// Reset daily counts at midnight
userSchema.statics.resetDailyCounts = async function() {
    await this.updateMany(
        {},
        {
            $set: {
                'messages.daily': 0,
                'voiceTime.daily': 0
            }
        }
    );
};

const UserModel = mongoose.model('User', userSchema);

module.exports = {
    DashboardConfig,
    AnalyticsConfig,
    GamingConfig,
    User: UserModel
}; 