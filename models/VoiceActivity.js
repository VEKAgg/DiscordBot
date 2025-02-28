const mongoose = require('mongoose');

const voiceActivitySchema = new mongoose.Schema({
    userId: {
        type: String,
        required: true,
        index: true
    },
    guildId: {
        type: String,
        required: true,
        index: true
    },
    channelId: {
        type: String,
        required: true
    },
    duration: {
        type: Number,
        required: true
    },
    startTime: {
        type: Date,
        required: true,
        index: true
    },
    endTime: {
        type: Date,
        required: true
    },
    activityDetails: {
        muted: Boolean,
        deafened: Boolean,
        streaming: Boolean,
        video: Boolean
    }
}, {
    timestamps: true
});

// Add indexes for common queries
voiceActivitySchema.index({ guildId: 1, startTime: -1 });
voiceActivitySchema.index({ userId: 1, guildId: 1, startTime: -1 });

module.exports = mongoose.model('VoiceActivity', voiceActivitySchema); 