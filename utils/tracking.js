const { logger } = require('./logger');
const UserActivity = require('../models/UserActivity');
const GuildStats = require('../models/GuildStats');

const trackingSystem = {
    async trackUserActivity(user, guild, activityType, details) {
        try {
            await UserActivity.findOneAndUpdate(
                { userId: user.id, guildId: guild.id },
                {
                    $push: {
                        activities: {
                            type: activityType,
                            details: details,
                            timestamp: new Date()
                        }
                    },
                    $inc: { [`${activityType}Count`]: 1 },
                    lastActive: new Date()
                },
                { upsert: true }
            );
        } catch (error) {
            logger.error('Error tracking user activity:', error);
        }
    },

    async trackGuildActivity(guild, activityType, data) {
        try {
            await GuildStats.findOneAndUpdate(
                { guildId: guild.id },
                {
                    $inc: {
                        [`${activityType}Count`]: 1,
                        totalActivities: 1
                    },
                    $push: {
                        recentActivities: {
                            type: activityType,
                            data: data,
                            timestamp: new Date()
                        }
                    }
                },
                { upsert: true }
            );
        } catch (error) {
            logger.error('Error tracking guild activity:', error);
        }
    }
};

module.exports = trackingSystem; 