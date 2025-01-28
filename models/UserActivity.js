const mongoose = require('mongoose');

const userActivitySchema = new mongoose.Schema({
    userId: { type: String, required: true },
    guildId: { type: String, required: true },
    activity: {
        richPresence: [{
            name: String,
            timestamp: { type: Date, default: Date.now },
            duration: { type: Number, default: 0 }
        }]
    }
});

// Calculate duration before saving
userActivitySchema.pre('save', function(next) {
    if (this.isModified('activity.richPresence')) {
        const presence = this.activity.richPresence[this.activity.richPresence.length - 1];
        if (presence && presence.timestamp) {
            presence.duration = Date.now() - presence.timestamp.getTime();
        }
    }
    next();
});

module.exports = mongoose.model('UserActivity', userActivitySchema); 