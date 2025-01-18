const mongoose = require('mongoose');

const userSchema = new mongoose.Schema({
    userId: String,
    guildId: String,
    username: String,
    economy: {
        balance: { type: Number, default: 0 },
        bank: { type: Number, default: 0 },
        lastDaily: Date
    },
    activity: {
        voiceTime: { type: Number, default: 0 },
        messageCount: { type: Number, default: 0 },
        lastSeen: Date,
        richPresence: [{
            game: String,
            timestamp: Date,
            duration: Number
        }]
    },
    statistics: {
        gamesPlayed: Map,
        favoriteGames: Array,
        peakActiveHours: Array
    }
});

const dealSchema = new mongoose.Schema({
    platform: String,
    title: String,
    originalPrice: Number,
    salePrice: Number,
    discount: Number,
    url: String,
    thumbnail: String,
    expiryDate: Date,
    postedDate: Date
});

module.exports = {
    User: mongoose.model('User', userSchema),
    Deal: mongoose.model('Deal', dealSchema)
};