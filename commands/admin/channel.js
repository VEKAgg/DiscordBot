const { SlashCommandBuilder, PermissionFlagsBits, ChannelType } = require('discord.js');
const { logger } = require('../../utils/logger');

module.exports = {
    name: 'channel',
    description: 'Manage server channels',
    category: 'admin',
    slashCommand: new SlashCommandBuilder()
        .setName('channel')
        .setDescription('Manage server channels')
        .setDefaultMemberPermissions(PermissionFlagsBits.ManageChannels)
        .addSubcommand(subcommand =>
            subcommand
                .setName('create')
                .setDescription('Create a new channel')
                .addStringOption(option =>
                    option.setName('type')
                        .setDescription('Type of channel to create')
                        .setRequired(true)
                        .addChoices(
                            { name: 'Dashboard', value: 'dashboard' },
                            { name: 'Logs', value: 'logs' },
                            { name: 'Staff', value: 'staff' }
                        ))
                .addStringOption(option =>
                    option.setName('name')
                        .setDescription('Custom channel name (optional)')
                        .setRequired(false)))
        .addSubcommand(subcommand =>
            subcommand
                .setName('delete')
                .setDescription('Delete a channel')
                .addChannelOption(option =>
                    option.setName('channel')
                        .setDescription('Channel to delete')
                        .setRequired(true))),

    async execute(interaction) {
        if (!interaction.member.permissions.has(PermissionFlagsBits.ManageChannels)) {
            return interaction.reply({
                content: 'You need Manage Channels permission to use this command.',
                ephemeral: true
            });
        }

        const subcommand = interaction.options.getSubcommand();

        try {
            switch (subcommand) {
                case 'create': {
                    const type = interaction.options.getString('type');
                    const customName = interaction.options.getString('name');

                    const channelTypes = {
                        'dashboard': { 
                            name: customName || 'bot-dashboard', 
                            topic: 'Server statistics and leaderboards',
                            type: ChannelType.GuildText
                        },
                        'logs': { 
                            name: customName || 'server-logs', 
                            topic: 'Server activity logging',
                            type: ChannelType.GuildText
                        },
                        'staff': { 
                            name: customName || 'staff-channel', 
                            topic: 'Staff notifications and controls',
                            type: ChannelType.GuildText
                        }
                    };

                    const channelConfig = channelTypes[type];
                    const channel = await interaction.guild.channels.create(channelConfig);

                    return interaction.reply({
                        content: `Created channel ${channel}`,
                        ephemeral: true
                    });
                }

                case 'delete': {
                    const channel = interaction.options.getChannel('channel');
                    await channel.delete();
                    return interaction.reply({
                        content: `Deleted channel #${channel.name}`,
                        ephemeral: true
                    });
                }
            }
        } catch (error) {
            logger.error('Channel command error:', error);
            return interaction.reply({
                content: 'An error occurred while managing channels.',
                ephemeral: true
            });
        }
    }
}; 