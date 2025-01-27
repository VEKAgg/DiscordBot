const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { NotificationConfig } = require('../../database');
const { logger } = require('../../utils/logger');

module.exports = {
    name: 'notifications',
    description: 'Configure server notifications',
    category: 'admin',
    slashCommand: new SlashCommandBuilder()
        .setName('notifications')
        .setDescription('Configure server notifications')
        .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
        .addSubcommand(subcommand =>
            subcommand
                .setName('setup')
                .setDescription('Set notification channel')
                .addChannelOption(option =>
                    option.setName('channel')
                        .setDescription('Channel for notifications')
                        .setRequired(true)))
        .addSubcommand(subcommand =>
            subcommand
                .setName('toggle')
                .setDescription('Toggle notification types')
                .addStringOption(option =>
                    option.setName('type')
                        .setDescription('Type of notification')
                        .setRequired(true)
                        .addChoices(
                            { name: 'Member Join/Leave', value: 'members' },
                            { name: 'Voice Activity', value: 'voice' },
                            { name: 'Level Up', value: 'levelup' }
                        ))
                .addBooleanOption(option =>
                    option.setName('enabled')
                        .setDescription('Enable or disable')
                        .setRequired(true))),

    async execute(interaction) {
        try {
            const subcommand = interaction.options.getSubcommand();

            switch (subcommand) {
                case 'setup': {
                    const channel = interaction.options.getChannel('channel');
                    await NotificationConfig.findOneAndUpdate(
                        { guildId: interaction.guildId },
                        { 
                            channelId: channel.id,
                            lastUpdate: new Date()
                        },
                        { upsert: true }
                    );
                    return interaction.reply({
                        content: `Notifications will be sent to ${channel}`,
                        ephemeral: true
                    });
                }

                case 'toggle': {
                    const type = interaction.options.getString('type');
                    const enabled = interaction.options.getBoolean('enabled');
                    
                    await NotificationConfig.findOneAndUpdate(
                        { guildId: interaction.guildId },
                        { 
                            [`types.${type}`]: enabled,
                            lastUpdate: new Date()
                        },
                        { upsert: true }
                    );
                    
                    return interaction.reply({
                        content: `${type} notifications have been ${enabled ? 'enabled' : 'disabled'}.`,
                        ephemeral: true
                    });
                }
            }
        } catch (error) {
            logger.error('Notifications command error:', error);
            return interaction.reply({
                content: 'An error occurred while configuring notifications.',
                ephemeral: true
            });
        }
    }
}; 