const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');
const { User } = require('../../database');
const { formatTime, formatStats } = require('../../utils/formatters');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'leaderboard',
    description: 'Shows various server leaderboards',
    category: 'utility',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    slashCommand: new SlashCommandBuilder()
        .setName('leaderboard')
        .setDescription('Shows various server leaderboards')
        .addStringOption(option =>
            option.setName('type')
                .setDescription('Type of leaderboard to show')
                .setRequired(false)
                .addChoices(
                    { name: 'Overall Activity', value: 'overall' },
                    { name: 'Gaming Time', value: 'gaming' },
                    { name: 'Voice Activity', value: 'voice' },
                    { name: 'Messages', value: 'messages' }
                ))
        .addStringOption(option =>
            option.setName('timeframe')
                .setDescription('Timeframe for the leaderboard')
                .setRequired(false)
                .addChoices(
                    { name: 'All Time', value: 'all' },
                    { name: 'Monthly', value: 'month' },
                    { name: 'Weekly', value: 'week' },
                    { name: 'Daily', value: 'day' }
                )),

    async execute(interaction) {
        const type = interaction.options.getString('type') || 'overall';
        const timeframe = interaction.options.getString('timeframe') || 'all';
        const guildId = interaction.guildId;

        const leaderboardTypes = {
            overall: {
                title: '🌟 Overall Activity',
                description: 'Combined activity score'
            },
            gaming: {
                title: '🎮 Gaming Time',
                description: 'Time spent gaming'
            },
            voice: {
                title: '🎤 Voice Activity',
                description: 'Time spent in voice channels'
            },
            messages: {
                title: '💬 Message Activity',
                description: 'Messages sent'
            }
        };

        if (!leaderboardTypes[type]) {
            return interaction.reply({
                content: `Invalid type! Available types: ${Object.keys(leaderboardTypes).join(', ')}`,
                ephemeral: true
            });
        }

        const users = await User.find({ guildId })
            .sort({ [`stats.${type}`]: -1 })
            .limit(10);

        const embed = new EmbedBuilder()
            .setTitle(leaderboardTypes[type].title)
            .setDescription(leaderboardTypes[type].description)
            .setColor('#2B2D31')
            .addFields({
                name: `Top 10 - ${timeframe.charAt(0).toUpperCase() + timeframe.slice(1)}`,
                value: users.map((user, index) => {
                    const value = formatStats(type, user.stats[type]);
                    return `${index + 1}. <@${user.userId}> - ${value}`;
                }).join('\n') || 'No data available'
            })
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await interaction.reply({ embeds: [embed] });
    }
}; 