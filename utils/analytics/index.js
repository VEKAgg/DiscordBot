const ConnectionAnalytics = require('./connectionAnalytics');
const InviteAnalytics = require('./inviteAnalytics');
const WelcomeAnalytics = require('./welcomeAnalytics');
const InviteAnalyzer = require('./inviteAnalyzer');
const CommandAnalytics = require('./commandAnalytics');
const { logger } = require('../logger');

class Analytics {
    static connection = ConnectionAnalytics;
    static invite = InviteAnalytics;
    static welcome = WelcomeAnalytics;
    static inviteAnalyzer = InviteAnalyzer;
    static command = CommandAnalytics;

    static async initialize() {
        try {
            logger.info('Initializing analytics systems...');
            
            // Initialize database connections and indexes
            await Promise.all([
                this.connection.initialize?.(),
                this.invite.initialize?.(),
                this.welcome.initialize?.(),
                this.inviteAnalyzer.initialize?.(),
                this.command.initialize?.()
            ]);

            // Set up periodic analytics tasks
            this.setupPeriodicTasks();
            
            logger.info('Analytics systems initialized successfully');
        } catch (error) {
            logger.error('Failed to initialize analytics:', error);
            throw error;
        }
    }

    static setupPeriodicTasks() {
        // Daily analytics aggregation
        setInterval(() => {
            this.command.aggregateDailyStats();
            this.welcome.generateInsights();
            this.connection.checkForInsights();
        }, 24 * 60 * 60 * 1000);
    }

    static async getStats(guildId, type = 'overview', timeframe = '7d') {
        try {
            const days = parseInt(timeframe) || 7;
            const stats = {
                overview: await this.connection.getOverviewStats(guildId, days),
                invite: await this.invite.getInviteStats(guildId, days),
                welcome: await this.welcome.getWelcomeStats(guildId, days),
                command: await this.command.getCommandStats(guildId, days)
            };

            return stats[type] || stats.overview;
        } catch (error) {
            logger.error('Analytics getStats error:', error);
            return {
                totalMembers: 0,
                activeMembers: 0,
                messageCount: 0,
                commandCount: 0,
                voiceMinutes: 0
            };
        }
    }
}

module.exports = Analytics; 