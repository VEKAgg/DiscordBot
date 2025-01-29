const { SlashCommandBuilder, EmbedBuilder, PermissionFlagsBits } = require('discord.js');
const Analytics = require('../../utils/analytics');
const { AnalyticsConfig } = require('../../database');
const { logger } = require('../../utils/logger');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'analytics',
    description: 'View and configure server analytics',
    category: 'admin',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    permissions: [PermissionFlagsBits.Administrator],
    slashCommand: new SlashCommandBuilder()
        .setName('analytics')
        .setDescription('View and configure server analytics')
        .setDefaultMemberPermissions(PermissionFlagsBits.Administrator)
        .addSubcommand(subcommand =>
            subcommand
                .setName('view')
                .setDescription('View server analytics')
                .addStringOption(option =>
                    option.setName('type')
                        .setDescription('Type of analytics to view')
                        .setRequired(false)
                        .addChoices(
                            { name: 'Overview', value: 'overview' },
                            { name: 'Messages', value: 'messages' },
                            { name: 'Voice', value: 'voice' },
                            { name: 'Members', value: 'members' },
                            { name: 'Commands', value: 'commands' },
                            { name: 'Invites', value: 'invites' }
                        ))
                .addStringOption(option =>
                    option.setName('timeframe')
                        .setDescription('Timeframe for analytics')
                        .setRequired(false)
                        .addChoices(
                            { name: '24 Hours', value: '1d' },
                            { name: '7 Days', value: '7d' },
                            { name: '30 Days', value: '30d' }
                        )))
        .addSubcommand(subcommand =>
            subcommand
                .setName('configure')
                .setDescription('Configure analytics settings')
                .addBooleanOption(option =>
                    option.setName('enabled')
                        .setDescription('Enable or disable analytics')
                        .setRequired(true))),

    async execute(interaction) {
        const subcommand = interaction.options.getSubcommand();

        try {
            if (subcommand === 'configure') {
                const enabled = interaction.options.getBoolean('enabled');
                await AnalyticsConfig.findOneAndUpdate(
                    { guildId: interaction.guild.id },
                    { enabled },
                    { upsert: true, new: true }
                );

                return interaction.reply({
                    content: `Analytics system has been ${enabled ? 'enabled' : 'disabled'} for this server.`,
                    ephemeral: true
                });
            }

            // Check if analytics is enabled
            const config = await AnalyticsConfig.findOne({ guildId: interaction.guild.id });
            if (!config?.enabled) {
                return interaction.reply({
                    content: 'Analytics is not enabled for this server. Use `/analytics configure enabled:true` to enable it.',
                    ephemeral: true
                });
            }

            const type = interaction.options.getString('type') || 'overview';
            const timeframe = interaction.options.getString('timeframe') || '7d';
            
            const analyticsData = await Analytics.getStats(interaction.guild.id, type, timeframe);
            if (!analyticsData) {
                return interaction.reply({
                    content: 'No analytics data available for the selected timeframe.',
                    ephemeral: true
                });
            }
            
            const embed = new EmbedBuilder()
                .setTitle(`Server Analytics - ${type.charAt(0).toUpperCase() + type.slice(1)}`)
                .setColor('#2B2D31')
                .setDescription(`Showing data for the last ${timeframe}`);

            // Format data based on type
            switch (type) {
                case 'commands':
                    embed.addFields(
                        { name: 'Total Commands', value: String(analyticsData.overview.totalCommands), inline: true },
                        { name: 'Success Rate', value: analyticsData.overview.successRate, inline: true },
                        { name: 'Daily Average', value: String(analyticsData.overview.avgCommandsPerDay), inline: true },
                        { name: 'Top Commands', value: analyticsData.topCommands.map(cmd => 
                            `${cmd.name}: ${cmd.uses} uses (${cmd.successRate} success)`).join('\n') }
                    );
                    break;
                default:
                    Object.entries(analyticsData).forEach(([key, value]) => {
                        embed.addFields({ name: key, value: String(value), inline: true });
                    });
            }

            embed.setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });
            await interaction.reply({ embeds: [embed] });

        } catch (error) {
            logger.error('Analytics Error:', error);
            await interaction.reply({
                content: 'An error occurred while processing analytics.',
                ephemeral: true
            });
        }
    }
};