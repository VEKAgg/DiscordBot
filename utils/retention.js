const UserStats = require('../models/UserStats');
const { logger } = require('./logger');

const retentionSystem = {
    async analyzeUserEngagement(guild) {
        try {
            const now = new Date();
            const thirtyDaysAgo = new Date(now - 30 * 24 * 60 * 60 * 1000);

            const stats = await UserStats.aggregate([
                {
                    $match: {
                        guildId: guild.id,
                        lastActive: { $gte: thirtyDaysAgo }
                    }
                },
                {
                    $group: {
                        _id: null,
                        activeUsers: { $sum: 1 },
                        totalActivities: { $sum: '$activityCount' },
                        avgSessionLength: { $avg: '$averageSessionLength' }
                    }
                }
            ]);

            return stats[0];
        } catch (error) {
            logger.error('Error analyzing user engagement:', error);
            return null;
        }
    },

    async identifyAtRiskUsers(guild) {
        // Identify users with declining engagement
        const twoWeeksAgo = new Date(Date.now() - 14 * 24 * 60 * 60 * 1000);
        
        try {
            return await UserStats.find({
                guildId: guild.id,
                lastActive: { $lt: twoWeeksAgo },
                activityCount: { $gt: 0 }
            }).sort({ lastActive: 1 });
        } catch (error) {
            logger.error('Error identifying at-risk users:', error);
            return [];
        }
    }
};

module.exports = retentionSystem; 