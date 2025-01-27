const BaseAnalytics = require('./baseAnalytics');
const { User } = require('../../database');
const StaffAlerts = require('../staffAlerts');

class ConnectionAnalytics extends BaseAnalytics {
    static async trackConnection(member, connections) {
        try {
            await this.updateGuildStats(member.guild.id, {
                $inc: { 'metrics.totalConnections': 1 },
                $push: {
                    'connections': {
                        userId: member.id,
                        platforms: Object.keys(connections),
                        timestamp: new Date()
                    }
                }
            });

            const insights = await this.checkForInsights(member.guild, connections);
            if (insights) {
                await StaffAlerts.send(member.guild, {
                    type: 'connection_insight',
                    priority: 'low',
                    content: 'New connection trends detected',
                    embed: insights
                });
            }
        } catch (error) {
            this.logError(error, 'trackConnection');
        }
    }

    static async getPlatformMetrics(platform, data) {
        // Reference from utils/connectionAnalytics.js
        startLine: 53
        endLine: 70
    }

    static async checkForInsights(guild, data) {
        const platforms = await this.getPopularPlatforms(guild.id);
        const totalUsers = await this.getTotalConnectedUsers(guild.id);
        
        if (totalUsers > 100 && platforms.length >= 3) {
            return this.createEmbed({
                title: '🔗 Connection Insights',
                fields: [
                    { name: 'Connected Users', value: totalUsers.toString(), inline: true },
                    { name: 'Top Platforms', value: platforms.join(', '), inline: true }
                ]
            });
        }
        return null;
    }

    static async analyzeConnectionTrends(guildId) {
        // Reference from utils/connectionAnalytics.js
        startLine: 88
        endLine: 105
    }

    static async getTotalConnectedUsers(guildId) {
        return this.aggregateData(
            User,
            {
                guildId,
                'connections.current': { $exists: true, $ne: {} }
            },
            {
                _id: null,
                count: { $sum: 1 }
            }
        ).then(result => result[0]?.count || 0);
    }

    static async getPopularPlatforms(guildId) {
        return this.aggregateData(
            User,
            { guildId },
            { 
                _id: '$platforms.k',
                count: { $sum: 1 }
            },
            { count: -1 },
            3
        ).then(platforms => platforms.map(p => p._id));
    }
}

module.exports = ConnectionAnalytics; 