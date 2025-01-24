const { EmbedBuilder, ChannelType } = require('discord.js');
const { fetchAPI } = require('./apiManager');
const { logger } = require('./logger');
const schedule = require('node-schedule');
const dashboardConfig = require('../config/dashboard');
const LeaderboardManager = require('../commands/leaderboard');
const { getLeaderboardData, createLeaderboardEmbed } = LeaderboardManager;
const WelcomeAnalytics = require('../utils/analytics/welcomeAnalytics');
const DashboardConfig = require('../models/DashboardConfig');

class DashboardManager {
    constructor(client) {
        this.client = client;
        this.messageIds = {};
        this.channelId = null;
        this.updateInterval = dashboardConfig.updateInterval;
        this.leaderboardManager = new LeaderboardManager(client);
    }

    async initialize() {
        try {
            const guild = this.client.guilds.cache.first();
            let config = await DashboardConfig.findOne({ guildId: guild.id });
            
            if (!config) {
                const dashboardChannel = this.findDashboardChannel(guild);
                
                if (!dashboardChannel) {
                    throw new Error('Dashboard channel not found. Please create a channel with "dashboard" or "stats" in its name.');
                }

                config = new DashboardConfig({
                    guildId: guild.id,
                    channelId: dashboardChannel.id,
                    messageIds: {}
                });
            }

            this.channelId = config.channelId;
            this.messageIds = config.messageIds;

            const channel = await this.client.channels.fetch(this.channelId);
            
            // Initialize embeds
            for (const [type, settings] of Object.entries(dashboardConfig.embedSettings)) {
                if (!this.messageIds[type]) {
                    const embed = await this.createEmbed(type);
                    const message = await channel.send({ embeds: [embed] });
                    this.messageIds[type] = message.id;
                    config.messageIds[type] = message.id;
                }
            }

            await config.save();
            this.scheduleUpdates();
            logger.info('Dashboard initialized successfully');
        } catch (error) {
            logger.error('Dashboard initialization error:', error);
        }
    }

    findDashboardChannel(guild) {
        const dashboardKeywords = ['dashboard', 'stats', 'leaderboard', 'bot-stats', 'ranking', '📊', '📈'];
        return guild.channels.cache.find(ch => 
            ch.type === ChannelType.GuildText && 
            dashboardKeywords.some(keyword => 
                ch.name.toLowerCase().replace(/[^a-z0-9]/g, '').includes(
                    keyword.toLowerCase().replace(/[^a-z0-9]/g, '')
                )
            )
        );
    }

    async createEmbed(type) {
        const guild = this.client.guilds.cache.first();
        
        switch (type) {
            case 'overall':
            case 'gaming':
            case 'voice':
            case 'text':
                const data = await this.leaderboardManager.getLeaderboardData(type, guild.id);
                return this.leaderboardManager.createEmbed(data, type, 'all', this.leaderboardManager.leaderboardTypes[type]);

            case 'github':
                const [commits, repo] = await Promise.all([
                    fetchAPI('github', '/repos/VEKAgg/DiscordBot/commits'),
                    fetchAPI('github', '/repos/VEKAgg/DiscordBot')
                ]).catch(() => [null, null]);

                if (!commits || !repo) {
                    throw new Error('Failed to fetch GitHub data');
                }

                return new EmbedBuilder()
                    .setTitle('🤖 Bot Updates')
                    .setDescription(commits.slice(0, 5).map(c => 
                        `• ${c.commit.message.split('\n')[0]}`
                    ).join('\n'))
                    .setColor('#0099ff')
                    .setTimestamp();

            case 'welcome':
                return await WelcomeAnalytics.generateInsights(guild);

            default:
                throw new Error(`Unknown dashboard type: ${type}`);
        }
    }

    scheduleUpdates() {
        schedule.scheduleJob(this.updateInterval, async () => {
            try {
                const channel = await this.client.channels.fetch(this.channelId);
                for (const [type, messageId] of Object.entries(this.messageIds)) {
                    const message = await channel.messages.fetch(messageId);
                    const embed = await this.createEmbed(type);
                    await message.edit({ embeds: [embed] });
                }
                logger.info('Dashboard updated successfully');
            } catch (error) {
                logger.error('Dashboard update error:', error);
            }
        });
    }

    async updateDashboard(guild) {
        try {
            const config = await DashboardConfig.findOne({ guildId: guild.id });
            if (!config?.channelId) return;

            const channel = guild.channels.cache.get(config.channelId);
            if (!channel) return;

            const dashboardTypes = ['overall', 'gaming', 'voice', 'text', 'github', 'welcome'];
            
            for (const type of dashboardTypes) {
                const embed = await this.createEmbed(type);
                if (!config.messageIds[type]) {
                    const msg = await channel.send({ embeds: [embed] });
                    config.messageIds[type] = msg.id;
                    await config.save();
                } else {
                    const msg = await channel.messages.fetch(config.messageIds[type])
                        .catch(() => null);
                    if (msg) await msg.edit({ embeds: [embed] });
                }
            }
        } catch (error) {
            logger.error('Dashboard update error:', error);
        }
    }
}

module.exports = DashboardManager; 