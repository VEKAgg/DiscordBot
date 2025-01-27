const mongoose = require('mongoose');
mongoose.set('bufferCommands', false); // Disable buffering for better memory usage
const { Schema } = mongoose;
const { logger } = require('./utils/logger');

// Add timestamps to all schemas
const baseOptions = { timestamps: true };

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
const GamingConfig = mongoose.models.GamingConfig || mongoose.model('GamingConfig', require('./models/GamingConfig').schema);
const NotificationConfig = mongoose.models.NotificationConfig || mongoose.model('NotificationConfig', require('./models/NotificationConfig').schema);

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

async function connect() {
    try {
        await mongoose.connect(process.env.MONGODB_URI, {
            maxPoolSize: 10,
            serverSelectionTimeoutMS: 5000,
            socketTimeoutMS: 45000
        });
        logger.info('Connected to MongoDB successfully');
        
        await mongoose.connection.db.admin().ping();
        return true;
    } catch (error) {
        logger.error('MongoDB connection error:', error.message);
        return false;
    }
}

// Add connection event handlers
mongoose.connection.on('disconnected', () => {
    logger.warn('MongoDB disconnected. Attempting to reconnect...');
    setTimeout(connect, 5000); // Try to reconnect after 5 seconds
});

mongoose.connection.on('error', (err) => {
    logger.error('MongoDB error:', err.message);
});

// Export all models and connection function
module.exports = {
    User,
    CommandLog,
    GuildAnalytics,
    WelcomeStats,
    BaseStats,
    Deal,
    GamingConfig,
    NotificationConfig,
    connect,
    getModel
};

