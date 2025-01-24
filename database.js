const mongoose = require('mongoose');
const { Schema } = mongoose;
const { logger } = require('./utils/logger');

// Define base stats schema
const baseStatsSchema = new Schema({
    guildId: {
        type: String,
        required: true,
        index: true
    },
    date: {
        type: Date,
        default: Date.now,
        index: true
    },
    updatedAt: {
        type: Date,
        default: Date.now
    }
}, { discriminatorKey: 'type' });

// Define guild analytics schema
const guildAnalyticsSchema = new Schema({
    metrics: {
        totalCommands: { type: Number, default: 0 },
        uniqueUsers: { type: Number, default: 0 },
        messageCount: { type: Number, default: 0 },
        errorCount: { type: Number, default: 0 },
        commandUsage: { type: Map, of: Number, default: new Map() },
        activeHours: { type: Map, of: Number, default: new Map() }
    }
});

// Define user schema
const userSchema = new Schema({
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

// Define command log schema
const commandLogSchema = new Schema({
    commandName: {
        type: String,
        required: true,
        index: true
    },
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
    args: [String],
    executionTime: Number,
    status: {
        type: String,
        enum: ['success', 'error'],
        default: 'success'
    },
    errorMessage: String,
    timestamp: {
        type: Date,
        default: Date.now,
        index: true
    }
});

// Define welcome stats schema
const welcomeStatsSchema = new Schema({
    guildId: { type: String, required: true, index: true },
    totalJoins: { type: Number, default: 0 },
    successfulDMs: { type: Number, default: 0 },
    verifiedJoins: { type: Number, default: 0 },
    hourlyJoins: { type: Map, of: Number, default: new Map() },
    dailyJoins: { type: Map, of: Number, default: new Map() },
    members: [{
        userId: String,
        joinedAt: Date,
        assignedRoles: [String],
        dmSuccess: Boolean,
        isVerified: Boolean
    }]
});

// Define deal schema
const dealSchema = new Schema({
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

// Create models
const BaseStats = mongoose.models.BaseStats || mongoose.model('BaseStats', baseStatsSchema);
const GuildAnalytics = BaseStats.discriminator('GuildAnalytics', guildAnalyticsSchema);
const User = mongoose.models.User || mongoose.model('User', userSchema);
const CommandLog = mongoose.models.CommandLog || mongoose.model('CommandLog', commandLogSchema);
const WelcomeStats = mongoose.models.WelcomeStats || mongoose.model('WelcomeStats', welcomeStatsSchema);
const Deal = mongoose.models.Deal || mongoose.model('Deal', dealSchema);

// Model getter function
function getModel(modelName) {
    if (mongoose.models[modelName]) {
        return mongoose.models[modelName];
    }

    switch (modelName) {
        case 'CommandLog':
            return mongoose.model('CommandLog', commandLogSchema);
        // Add other models here as needed
        default:
            throw new Error(`Unknown model: ${modelName}`);
    }
}

// Export all models and connection function
module.exports = {
    User,
    CommandLog,
    GuildAnalytics,
    WelcomeStats,
    BaseStats,
    Deal,
    connect: async () => {
        try {
            await mongoose.connect(process.env.MONGODB_URI);
            logger.info('Database connected successfully');
        } catch (error) {
            logger.error('Database connection failed:', error);
            throw error;
        }
    },
    getModel
};

