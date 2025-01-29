const mongoose = require('mongoose');
const { Schema } = mongoose;
const { logger } = require('./utils/logger');

// Remove deprecated options and use new connection style
async function connectDB(uri) {
    try {
        await mongoose.connect(uri);
        logger.info('MongoDB connection established');
    } catch (error) {
        logger.error('MongoDB connection error:', error);
        throw error;
    }
}

// Base options for all schemas
const baseOptions = {
    timestamps: true
};

// Update connection options for MongoDB 8.x compatibility
const connectionOptions = {
    maxPoolSize: 10,
    minPoolSize: 2,
    socketTimeoutMS: 45000,
    serverSelectionTimeoutMS: 5000,
    family: 4, // Use IPv4, skip trying IPv6
    heartbeatFrequencyMS: 30000
};

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

// Add indexes for frequently queried fields
baseStatsSchema.index({ guildId: 1, date: 1 }, { unique: true });

// Define guild analytics schema
const guildAnalyticsSchema = new Schema({
    guildId: { type: String, required: true, unique: true },
    memberCount: { type: Number, default: 0 },
    messageCount: { type: Number, default: 0 },
    commandCount: { type: Number, default: 0 },
    lastActivity: { type: Date, default: Date.now }
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
        lastSeen: { type: Date, index: true },
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
}, baseOptions);

// Add indexes for frequently queried fields
userSchema.index({ userId: 1, guildId: 1 }, { unique: true });

// Add error handling middleware
userSchema.post('save', function(error, doc, next) {
    if (error.name === 'MongoError' && error.code === 11000) {
        next(new Error('Duplicate key error'));
    } else {
        next(error);
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
        default: Date.now
    }
});

// Add indexes for frequently queried fields
commandLogSchema.index({ commandName: 1, timestamp: 1 });
commandLogSchema.index({ timestamp: 1 }, { expireAfterSeconds: 2592000 }); // 30 days TTL

// Define welcome stats schema
const welcomeStatsSchema = new Schema({
    guildId: { type: String, required: true, index: true },
    totalJoins: { type: Number, default: 0 },
    successfulDMs: { type: Number, default: 0 },
    verifiedJoins: { type: Number, default: 0 },
    hourlyJoins: { type: Map, of: Number, default: new Map() },
    dailyJoins: { type: Map, of: Number, default: new Map() },
    members: [{
        userId: { type: String, required: true },
        joinedAt: { type: Date, default: Date.now },
        assignedRoles: [{ type: String, validate: /^[0-9]{17,19}$/ }],
        dmSuccess: { type: Boolean, default: false },
        isVerified: { type: Boolean, default: false }
    }]
}, baseOptions);

// Define deal schema before using it
const dealSchema = new Schema({
    platform: String,
    title: String,
    originalPrice: Number,
    salePrice: Number,
    discount: Number,
    url: { type: String, unique: true },
    thumbnail: String,
    expiryDate: Date,
    postedDate: { type: Date, default: Date.now }
});

// Create models with a check to prevent recompilation
const models = {};

// Helper function to safely get or create a model
function getModel(name, schema) {
    return mongoose.models[name] || mongoose.model(name, schema);
}

// Export models through getter functions to prevent duplicate compilation
module.exports = {
    connectDB,
    baseOptions,
    get Deal() {
        return getModel('Deal', dealSchema);
    },
    get GuildAnalytics() {
        return getModel('GuildAnalytics', guildAnalyticsSchema);
    },
    User: userSchema,
    CommandLog: commandLogSchema,
    WelcomeStats: welcomeStatsSchema,
    BaseStats: baseStatsSchema,
    GamingConfig: require('./models/GamingConfig').schema,
    NotificationConfig: require('./models/NotificationConfig').schema,
    getModel
};

