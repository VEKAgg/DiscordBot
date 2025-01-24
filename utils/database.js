const mongoose = require('mongoose');

const activitySchema = new mongoose.Schema({
    messageCount: { type: Number, default: 0 },
    voiceTime: { type: Number, default: 0 },
    richPresence: [{
        name: String,
        details: String,
        startTimestamp: Date,
        endTimestamp: Date
    }],
    dailyStreak: { type: Number, default: 0 },
    lastActive: { type: Date },
    reactionsGiven: { type: Number, default: 0 },
    reactionsReceived: { type: Number, default: 0 },
    mentionsReceived: { type: Number, default: 0 }
});

const userSchema = new mongoose.Schema({
    userId: { type: String, required: true },
    guildId: { type: String, required: true },
    activity: { type: activitySchema, default: () => ({}) },
    lastPresenceUpdate: Date
}, { 
    timestamps: true 
});

userSchema.index({ userId: 1, guildId: 1 }, { unique: true });

module.exports = mongoose.model('User', userSchema);