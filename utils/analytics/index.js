const ConnectionAnalytics = require('./connectionAnalytics');
const InviteAnalytics = require('./inviteAnalytics');
const WelcomeAnalytics = require('./welcomeAnalytics');
const InviteAnalyzer = require('./inviteAnalyzer');
const CommandAnalytics = require('./commandAnalytics');
const { logger } = require('../logger');
const { User, CommandLog } = require('../../database');

class Analytics {
    static connection = ConnectionAnalytics;
    static invite = InviteAnalytics;
    static welcome = WelcomeAnalytics;
    static inviteAnalyzer = InviteAnalyzer;
    static command = CommandAnalytics;

    static async initialize() {
        try {
            logger.info('Initializing analytics systems...');
            await Promise.all([
                this.connection.initialize?.(),
                this.invite.initialize?.(),
                this.welcome.initialize?.(),
                this.inviteAnalyzer.initialize?.(),
                this.command.initialize?.()
            ]);
            this.setupPeriodicTasks();
            logger.info('Analytics systems initialized successfully');
        } catch (error) {
            logger.error('Failed to initialize analytics:', error);
            throw error;
        }
    }

    static setupPeriodicTasks() {
        setInterval(() => {
            this.command.aggregateDailyStats();
            this.welcome.generateInsights();
            this.connection.checkForInsights();
        }, 24 * 60 * 60 * 1000);
    }

    static async getStats(guildId, type = 'overview', timeframe = '7d') {
        try {
            switch (type) {
                case 'overview':
                    return await this.command.getGuildStats(guildId, type, timeframe);
                case 'welcome':
                    return await this.welcome.getGuildStats(guildId);
                case 'connections':
                    return await this.connection.getGuildStats(guildId, timeframe);
                case 'invites':
                    return await this.invite.getGuildStats(guildId, timeframe);
                default:
                    return await this.command.getGuildStats(guildId, type, timeframe);
            }
        } catch (error) {
            logger.error('Analytics getStats error:', error);
            return null;
        }
    }

    static async cleanup() {
        const maxAge = 30 * 24 * 60 * 60 * 1000;
        const cutoff = new Date(Date.now() - maxAge);
        await Promise.all([
            this.command.cleanupOldData(cutoff),
            this.welcome.cleanupOldData(cutoff),
            this.connection.cleanupOldData(cutoff)
        ]);
    }

    static async healthCheck() {
        const results = await Promise.all([
            this.connection.ping(),
            this.invite.ping(),
            this.welcome.ping()
        ]);
        return results.every(result => result === true);
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