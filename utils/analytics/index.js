const { User, CommandLog, GuildAnalytics } = require('../../database');
const { logger } = require('../logger');
const StaffAlerts = require('../staffAlerts');

class BaseAnalytics {
    static async aggregateData(model, match, group, sort = null, limit = null) {
        try {
            let pipeline = [{ $match: match }, { $group: group }];
            if (sort) pipeline.push({ $sort: sort });
            if (limit) pipeline.push({ $limit: limit });
            return await model.aggregate(pipeline);
        } catch (error) {
            this.logError(error, 'aggregateData');
            return [];
        }
    }

    static logError(error, method) {
        logger.error(`Analytics Error in ${method}:`, error);
    }

    static getTimeframeDate(timeframe) {
        const now = Date.now();
        switch (timeframe) {
            case '1d': return new Date(now - 24 * 60 * 60 * 1000);
            case '7d': return new Date(now - 7 * 24 * 60 * 60 * 1000);
            case '30d': return new Date(now - 30 * 24 * 60 * 60 * 1000);
            default: return new Date(now - 7 * 24 * 60 * 60 * 1000);
        }
    }
}

class Analytics {
    static async initialize() {
        try {
            logger.info('Initializing analytics systems...');
            this.setupPeriodicTasks();
            logger.info('Analytics systems initialized successfully');
        } catch (error) {
            logger.error('Failed to initialize analytics:', error);
            throw error;
        }
    }

    static setupPeriodicTasks() {
        setInterval(() => {
            this.aggregateDailyStats();
            this.generateWelcomeInsights();
            this.checkConnectionInsights();
            this.cleanup();
        }, 24 * 60 * 60 * 1000);
    }

    // Command Analytics
    static async aggregateDailyStats() {
        try {
            const guilds = await GuildAnalytics.distinct('guildId');
            await Promise.all(guilds.map(guildId => this.getGuildStats(guildId)));
        } catch (error) {
            logger.error('Error in aggregateDailyStats:', error);
        }
    }

    // Welcome Analytics
    static async calculateRetentionRate(guildId) {
        const thirtyDaysAgo = this.getTimeframeDate('30d');
        const stats = await this.getGuildStats(guildId);
        const joinedUsers = stats.members.filter(m => m.joinedAt < thirtyDaysAgo);
        if (!joinedUsers.length) return 0;

        const stillPresent = await BaseAnalytics.aggregateData(
            User,
            {
                guildId,
                userId: { $in: joinedUsers.map(u => u.userId) },
                leftAt: null
            },
            { _id: null, count: { $sum: 1 } }
        );

        return (stillPresent[0]?.count || 0) / joinedUsers.length * 100;
    }

    // Invite Analytics
    static async analyzeInvites(guild, inviter, invitedUser) {
        try {
            const timeWindow = 24 * 60 * 60 * 1000;
            const stats = await this.getInviterStats(inviter.id, guild.id, timeWindow);
            
            if (this.detectSuspiciousPatterns(stats)) {
                await StaffAlerts.sendAlert(guild, 'Suspicious invite activity detected', {
                    inviter,
                    stats
                });
            }
        } catch (error) {
            logger.error('Error in analyzeInvites:', error);
        }
    }

    static async getStats(guildId, type = 'overview', timeframe = '7d') {
        try {
            const startDate = BaseAnalytics.getTimeframeDate(timeframe);
            const baseStats = await this.getGuildStats(guildId, startDate);

            switch (type) {
                case 'overview':
                    return {
                        ...baseStats,
                        retentionRate: await this.calculateRetentionRate(guildId)
                    };
                case 'welcome':
                    return {
                        joins: baseStats.totalJoins,
                        leaves: baseStats.totalLeaves,
                        retention: await this.calculateRetentionRate(guildId)
                    };
                case 'invites':
                    return {
                        total: baseStats.totalInvites,
                        active: baseStats.activeInvites,
                        conversion: await this.calculateConversionRate(guildId, startDate)
                    };
                default:
                    return baseStats;
            }
        } catch (error) {
            logger.error('Analytics getStats error:', error);
            return null;
        }
    }

    static async cleanup() {
        const maxAge = 30 * 24 * 60 * 60 * 1000;
        const cutoff = new Date(Date.now() - maxAge);
        
        try {
            await Promise.all([
                CommandLog.deleteMany({ timestamp: { $lt: cutoff } }),
                GuildAnalytics.deleteMany({ timestamp: { $lt: cutoff } })
            ]);
        } catch (error) {
            logger.error('Analytics cleanup error:', error);
        }
    }
}

module.exports = Analytics;

// Add to utils/logger.js
const winston = require('winston');
const DailyRotateFile = require('winston-daily-rotate-file');

const transport = new DailyRotateFile({
    filename: '/var/log/vekabot/%DATE%.log',
    datePattern: 'YYYY-MM-DD',
    maxSize: '20m',
    maxFiles: '14d',
    compression: 'gzip'
});

// Add to utils/monitor.js
const os = require('os');
const pidusage = require('pidusage');

class SystemMonitor {
    static async getMetrics() {
        const stats = await pidusage(process.pid);
        return {
            cpu: stats.cpu,
            memory: stats.memory / 1024 / 1024,
            uptime: process.uptime(),
            loadAvg: os.loadavg(),
            freeMemory: os.freemem() / 1024 / 1024
        };
    }
}