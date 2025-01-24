const { EmbedBuilder, PermissionFlagsBits } = require('discord.js');
const DashboardConfig = require('../../models/DashboardConfig');
const AnalyticsConfig = require('../../models/AnalyticsConfig');
const GamingConfig = require('../../models/GamingConfig');
const NotificationConfig = require('../../models/NotificationConfig');
const { logger } = require('../../utils/logger');

module.exports = {
    name: 'setup',
    description: 'Setup bot features for your server',
    permissions: [PermissionFlagsBits.Administrator],
    async execute(message) {
        const setupEmbed = new EmbedBuilder()
            .setTitle('🔧 Bot Setup')
            .setDescription('Let\'s set up the bot for your server! React to configure each feature:')
            .addFields([
                { name: '📊 Dashboard', value: 'Server statistics and leaderboards', inline: true },
                { name: '📈 Analytics', value: 'Track server growth and activity', inline: true },
                { name: '🎮 Gaming', value: 'Game presence tracking', inline: true },
                { name: '🔔 Notifications', value: 'Configure alert channels', inline: true }
            ])
            .setColor('#FFA500'); // Orange color for setup

        message.channel.sendTyping();
        const setupMsg = await message.channel.send({ embeds: [setupEmbed] });
        const reactions = ['📊', '📈', '🎮', '🔔'];
        
        await Promise.all(reactions.map(r => setupMsg.react(r)));

        const collector = setupMsg.createReactionCollector({
            filter: (reaction, user) => 
                reactions.includes(reaction.emoji.name) && 
                user.id === message.author.id,
            time: 300000
        });

        collector.on('collect', async (reaction, user) => {
            try {
                const setupFunctions = {
                    '📊': this.setupDashboard,
                    '📈': this.setupAnalytics,
                    '🎮': this.setupGaming,
                    '🔔': this.setupNotifications
                };

                const selectedFunction = setupFunctions[reaction.emoji.name];
                if (selectedFunction) {
                    await selectedFunction.call(this, message);
                    await reaction.users.remove(user.id);
                }
            } catch (error) {
                logger.error('Setup error:', error);
                message.channel.send('Failed to setup selected feature. Please try again.');
            }
        });

        collector.on('end', () => {
            setupMsg.reactions.removeAll().catch(error => logger.error('Failed to clear reactions:', error));
        });
    },

    async setupDashboard(message) {
        const channel = await message.channel.send('Please mention the channel for the dashboard (#channel)');
        const response = await message.channel.awaitMessages({
            filter: m => m.author.id === message.author.id,
            max: 1,
            time: 30000
        });
        
        if (!response.size) return message.reply('Setup timed out.');
        
        const targetChannel = response.first().mentions.channels.first();
        if (!targetChannel) return message.reply('Please mention a valid channel.');
        
        await DashboardConfig.findOneAndUpdate(
            { guildId: message.guild.id },
            { channelId: targetChannel.id },
            { upsert: true }
        );
        
        message.reply(`Dashboard will be displayed in ${targetChannel}`);
    },

    async setupAnalytics(message) {
        await AnalyticsConfig.findOneAndUpdate(
            { guildId: message.guild.id },
            { $set: { enabled: true } },
            { upsert: true }
        );
        message.reply('Analytics system has been enabled.');
    },

    async setupGaming(message) {
        await GamingConfig.findOneAndUpdate(
            { guildId: message.guild.id },
            { $set: { enabled: true } },
            { upsert: true }
        );
        message.reply('Game tracking has been enabled.');
    },

    async setupNotifications(message) {
        const channel = await message.channel.send('Please mention the channel for notifications (#channel)');
        const response = await message.channel.awaitMessages({
            filter: m => m.author.id === message.author.id,
            max: 1,
            time: 30000
        });
        
        if (!response.size) return message.reply('Setup timed out.');
        
        const targetChannel = response.first().mentions.channels.first();
        if (!targetChannel) return message.reply('Please mention a valid channel.');
        
        await NotificationConfig.findOneAndUpdate(
            { guildId: message.guild.id },
            { channelId: targetChannel.id },
            { upsert: true }
        );
        
        message.reply(`Notifications will be sent to ${targetChannel}`);
    }
}; 