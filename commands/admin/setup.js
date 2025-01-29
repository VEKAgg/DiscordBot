const { SlashCommandBuilder, EmbedBuilder, PermissionFlagsBits } = require('discord.js');
const { DashboardConfig, GamingConfig, NotificationConfig } = require('../../database');
const { logger } = require('../../utils/logger');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'setup',
    description: 'Configure bot settings',
    category: 'admin',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    permissions: [PermissionFlagsBits.Administrator],
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
                        .setDescription('Channel to display the dashboard')
                        .setRequired(true)))
        .addSubcommand(subcommand =>
            subcommand
                .setName('notifications')
                .setDescription('Configure notification settings')
                .addChannelOption(option =>
                    option.setName('channel')
                        .setDescription('Channel for notifications')
                        .setRequired(true))
                .addStringOption(option =>
                    option.setName('type')
                        .setDescription('Type of notifications')
                        .setRequired(true)
                        .addChoices(
                            { name: 'All', value: 'all' },
                            { name: 'Moderation', value: 'mod' },
                            { name: 'Welcome', value: 'welcome' },
                            { name: 'System', value: 'system' }
                        )))
        .addSubcommand(subcommand =>
            subcommand
                .setName('gaming')
                .setDescription('Enable game tracking')
                .addBooleanOption(option =>
                    option.setName('enabled')
                        .setDescription('Enable or disable game tracking')
                        .setRequired(true)),

    async execute(interaction) {
        const subcommand = interaction.options.getSubcommand();
        const channel = interaction.options.getChannel('channel');

        try {
            switch (subcommand) {
                case 'dashboard': {
                    await DashboardConfig.findOneAndUpdate(
                        { guildId: interaction.guild.id },
                        { channelId: channel.id },
                        { upsert: true }
                    );
                    return interaction.reply({
                        content: `Dashboard will be displayed in ${channel}`,
                        ephemeral: true
                    });
                }
                
                case 'notifications': {
                    const type = interaction.options.getString('type');
                    await NotificationConfig.findOneAndUpdate(
                        { guildId: interaction.guild.id },
                        { 
                            channelId: channel.id,
                            type: type
                        },
                        { upsert: true }
                    );
                    return interaction.reply({
                        content: `${type} notifications will be sent to ${channel}`,
                        ephemeral: true
                    });
                }

                case 'gaming': {
                    const enabled = interaction.options.getBoolean('enabled');
                    await GamingConfig.findOneAndUpdate(
                        { guildId: interaction.guild.id },
                        { enabled },
                        { upsert: true }
                    );
                    return interaction.reply({
                        content: `Game tracking has been ${enabled ? 'enabled' : 'disabled'}`,
                        ephemeral: true
                    });
                }
            }
        } catch (error) {
            logger.error('Setup command error:', error);
            return interaction.reply({
                content: 'An error occurred while updating settings.',
                ephemeral: true
            });
        }
    }
}; 