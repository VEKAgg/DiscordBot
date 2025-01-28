const { SlashCommandBuilder, EmbedBuilder, PermissionFlagsBits } = require('discord.js');
const { DashboardConfig, AnalyticsConfig, GamingConfig } = require('../../database');
const NotificationConfig = require('../../models/NotificationConfig');
const { logger } = require('../../utils/logger');

module.exports = {
    name: 'setup',
    description: 'Configure bot settings for the server',
    category: 'admin',
    slashCommand: new SlashCommandBuilder()
        .setName('setup')
        .setDescription('Configure bot settings')
        .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
        .addSubcommand(subcommand =>
            subcommand
                .setName('dashboard')
                .setDescription('Set up the server dashboard')
                .addChannelOption(option =>
                    option.setName('channel')
                        .setDescription('Channel for the dashboard')
                        .setRequired(true)))
        .addSubcommand(subcommand =>
            subcommand
                .setName('analytics')
                .setDescription('Enable server analytics')
                .addBooleanOption(option =>
                    option.setName('enabled')
                        .setDescription('Enable or disable analytics')
                        .setRequired(true)))
        .addSubcommand(subcommand =>
            subcommand
                .setName('gaming')
                .setDescription('Enable game tracking')
                .addBooleanOption(option =>
                    option.setName('enabled')
                        .setDescription('Enable or disable game tracking')
                        .setRequired(true))),

    async execute(interaction) {
        if (!interaction.member.permissions.has(PermissionFlagsBits.Administrator)) {
            return interaction.reply({ 
                content: 'You need Administrator permissions to use this command.',
                ephemeral: true 
            });
        }

        const subcommand = interaction.options.getSubcommand();

        try {
            switch (subcommand) {
                case 'dashboard': {
                    const channel = interaction.options.getChannel('channel');
                    await DashboardConfig.findOneAndUpdate(
                        { guildId: interaction.guildId },
                        { 
                            channelId: channel.id,
                            lastUpdate: new Date()
                        },
                        { upsert: true }
                    );
                    return interaction.reply({
                        content: `Dashboard will be displayed in ${channel}`,
                        ephemeral: true
                    });
                }
                
                case 'analytics': {
                    const enabled = interaction.options.getBoolean('enabled');
                    await AnalyticsConfig.findOneAndUpdate(
                        { guildId: interaction.guildId },
                        { 
                            enabled,
                            lastUpdate: new Date()
                        },
                        { upsert: true }
                    );
                    return interaction.reply({
                        content: `Analytics system has been ${enabled ? 'enabled' : 'disabled'}.`,
                        ephemeral: true
                    });
                }
                
                case 'gaming': {
                    const enabled = interaction.options.getBoolean('enabled');
                    await GamingConfig.findOneAndUpdate(
                        { guildId: interaction.guildId },
                        { 
                            enabled,
                            lastUpdate: new Date()
                        },
                        { upsert: true }
                    );
                    return interaction.reply({
                        content: `Game tracking has been ${enabled ? 'enabled' : 'disabled'}.`,
                        ephemeral: true
                    });
                }
            }
        } catch (error) {
            logger.error('Setup command error:', error);
            return interaction.reply({
                content: 'An error occurred while setting up the feature. Please try again.',
                ephemeral: true
            });
        }
    },

    async setupNotifications(interaction) {
        const channel = await interaction.channel.send('Please mention the channel for notifications (#channel)');
        const response = await interaction.channel.awaitMessages({
            filter: m => m.author.id === interaction.user.id,
            max: 1,
            time: 30000
        });
        
        if (!response.size) return interaction.reply('Setup timed out.');
        
        const targetChannel = response.first().mentions.channels.first();
        if (!targetChannel) return interaction.reply('Please mention a valid channel.');
        
        await NotificationConfig.findOneAndUpdate(
            { guildId: interaction.guildId },
            { channelId: targetChannel.id },
            { upsert: true }
        );
        
        interaction.reply(`Notifications will be sent to ${targetChannel}`);
    }
}; 