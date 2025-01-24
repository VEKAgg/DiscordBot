const { ActivityType } = require('discord.js');
const { richPresence, botDescription, scheduledTaskCron } = require('../config');
const { logger } = require('../utils/logger');
const Analytics = require('../utils/analytics');
const { runBackgroundChecks } = require('../utils/backgroundMonitor');
const schedule = require('node-schedule');
const DashboardManager = require('../utils/dashboardManager');
const ChannelVerifier = require('../utils/channelVerifier');
const LoggingManager = require('../utils/loggingManager');
const StatusManager = require('../utils/statusManager');

module.exports = {
    name: 'ready',
    once: true,
    async execute(client) {
        try {
            client.statusManager = new StatusManager(client);
            client.statusManager.start();
            
            const guilds = client.guilds.cache.size;
            const users = client.guilds.cache.reduce((acc, guild) => acc + guild.memberCount, 0);
            
            logger.info(`🟢 ${client.user.tag} is online!`);
            logger.info(`Serving ${users} users in ${guilds} servers`);
            
            // Initialize systems
            await Promise.all([
                client.analytics?.initialize(),
                client.dashboard?.initialize()
            ]);
        } catch (error) {
            logger.error('Startup error:', error);
        }
    },
};
