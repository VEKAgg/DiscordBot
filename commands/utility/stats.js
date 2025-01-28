const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');
const { User } = require('../../database');
const { formatTime } = require('../../utils/formatters');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'stats',
    description: 'Shows user statistics',
    category: 'utility',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    slashCommand: new SlashCommandBuilder()
        .setName('stats')
        .setDescription('Shows user statistics')
        .addUserOption(option =>
            option.setName('user')
                .setDescription('User to check stats for')
                .setRequired(false))
        .addStringOption(option =>
            option.setName('type')
                .setDescription('Type of statistics to view')
                .setRequired(false)
                .addChoices(
                    { name: 'Overview', value: 'overview' },
                    { name: 'Messages', value: 'messages' },
                    { name: 'Voice', value: 'voice' },
                    { name: 'Members', value: 'members' }
                ))
        .addStringOption(option =>
            option.setName('timeframe')
                .setDescription('Timeframe for statistics')
                .setRequired(false)
                .addChoices(
                    { name: '24 Hours', value: '1d' },
                    { name: '7 Days', value: '7d' },
                    { name: '30 Days', value: '30d' }
                )),

    async execute(interaction) {
        const targetUser = interaction.options.getUser('user') || interaction.user;
        const userData = await User.findOne({ 
            userId: targetUser.id,
            guildId: interaction.guildId
        });

        if (!userData) {
            return interaction.reply({
                content: 'No statistics found for this user.',
                ephemeral: true
            });
        }

        const embed = new EmbedBuilder()
            .setTitle(`${targetUser.tag}'s Statistics`)
            .setThumbnail(targetUser.displayAvatarURL({ dynamic: true }))
            .setColor('#2B2D31')
            .addFields([
                { name: 'Messages Sent', value: userData.stats?.messages?.toString() || '0', inline: true },
                { name: 'Voice Time', value: formatTime(userData.stats?.voiceTime || 0), inline: true },
                { name: 'Gaming Time', value: formatTime(userData.stats?.gamingTime || 0), inline: true }
            ])
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await interaction.reply({ embeds: [embed] });
    }
};
