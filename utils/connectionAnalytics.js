const { EmbedBuilder } = require('discord.js');
const { User } = require('../database');
const { logger } = require('./logger');

class ConnectionAnalytics {
    static async trackConnection(member, connections) {
        try {
            const analyticsData = {
                userId: member.id,
                guildId: member.guild.id,
                timestamp: new Date(),
                platforms: {},
                metrics: {}
            };

            // Track each platform's data
            for (const [platform, data] of Object.entries(connections)) {
                if (data.verified) {
                    analyticsData.platforms[platform] = {
                        verified: true,
                        metrics: await this.getPlatformMetrics(platform, data.data),
                        lastUpdated: new Date()
                    };
                }
            }

            // Update database
            await User.findOneAndUpdate(
                { 
                    userId: member.id,
                    guildId: member.guild.id 
                },
                {
                    $push: { 
                        'connections.history': analyticsData 
                    },
                    $set: {
                        'connections.current': analyticsData.platforms
                    }
                },
                { upsert: true }
            );

            // Generate insights if needed
            await this.checkForInsights(member.guild, analyticsData);

        } catch (error) {
            logger.error('Connection analytics error:', error);
        }
    }

    static async getPlatformMetrics(platform, data) {
        const metrics = {};
        
        switch (platform) {
            case 'github':
                metrics.repos = data?.public_repos || 0;
                metrics.followers = data?.followers || 0;
                metrics.contributions = await this.getGithubContributions(data);
                break;
            case 'twitch':
                metrics.followers = data?.followers || 0;
                metrics.avgViewers = data?.average_viewers || 0;
                metrics.streamTime = data?.total_stream_time || 0;
                break;
            // Add other platforms...
        }

        return metrics;
    }

    static async checkForInsights(guild, data) {
        const insights = await this.analyzeConnectionTrends(guild.id);
        if (insights.significantChanges.length > 0) {
            await StaffAlerts.send(guild, {
                type: 'connection_insight',
                priority: 'low',
                content: 'New connection trends detected',
                data: {
                    trends: insights.significantChanges.join('\n'),
                    total_connected: insights.totalConnected,
                    most_popular: insights.popularPlatforms.join(', ')
                }
            });
        }
    }

    static async analyzeConnectionTrends(guildId) {
        // Reference to leaderboard.js for scoring methods:
        // startLine: 187
        // endLine: 246

        const recentData = await User.aggregate([
            { $match: { guildId } },
            { $unwind: '$connections.history' },
            { $sort: { 'connections.history.timestamp': -1 } },
            { $limit: 100 }
        ]);

        return {
            significantChanges: this.detectSignificantChanges(recentData),
            totalConnected: await this.getTotalConnectedUsers(guildId),
            popularPlatforms: await this.getPopularPlatforms(guildId)
        };
    }
}

module.exports = ConnectionAnalytics; 