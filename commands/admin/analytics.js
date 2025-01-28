const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const Analytics = require('../../utils/analytics');
const { logger } = require('../../utils/logger');
const { createEmbed } = require('../../utils/embedCreator');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'analytics',
    description: 'View server analytics',
    category: 'admin',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    permissions: [PermissionFlagsBits.Administrator],
    slashCommand: new SlashCommandBuilder()
        .setName('analytics')
        .setDescription('View server analytics')
        .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
        .addStringOption(option =>
            option.setName('type')
                .setDescription('Type of analytics to view')
                .setRequired(false)
                .addChoices(
                    { name: 'Overview', value: 'overview' },
                    { name: 'Messages', value: 'messages' },
                    { name: 'Voice', value: 'voice' },
                    { name: 'Members', value: 'members' }
                ))
        .addStringOption(option =>
            option.setName('timeframe')
                .setDescription('Timeframe for analytics')
                .setRequired(false)
                .addChoices(
                    { name: '24 Hours', value: '1d' },
                    { name: '7 Days', value: '7d' },
                    { name: '30 Days', value: '30d' }
                )),

    async execute(interaction) {
        try {
            const type = interaction.options.getString('type') || 'overview';
            const timeframe = interaction.options.getString('timeframe') || '7d';
            
            const stats = await Analytics.getStats(interaction.guildId, type, timeframe);
            
            if (!stats) {
                return interaction.reply({
                    content: 'No analytics data available.',
                    ephemeral: true
                });
            }

            const embed = createEmbed({
                title: `📊 Server Analytics - ${type.charAt(0).toUpperCase() + type.slice(1)}`,
                description: 'Server activity statistics',
                fields: Object.entries(stats).map(([key, value]) => ({
                    name: key.charAt(0).toUpperCase() + key.slice(1).replace(/([A-Z])/g, ' $1'),
                    value: typeof value === 'object' ? 
                        JSON.stringify(value, null, 2).replace(/[{}"]/g, '') : 
                        String(value),
                    inline: true
                })),
                color: '#2B2D31',
                footer: { text: `Contributed by ${this.contributor} • ${getRandomFooter()}` }
            });

            await interaction.reply({ embeds: [embed] });
        } catch (error) {
            logger.error('Analytics command error:', error);
            return interaction.reply({
                content: 'An error occurred while fetching analytics.',
                ephemeral: true
            });
        }
    }
};