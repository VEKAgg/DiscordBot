const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');
const { User } = require('../../database');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'xpleaderboard',
    description: 'Shows the server XP leaderboard',
    category: 'utility',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    slashCommand: new SlashCommandBuilder()
        .setName('xpleaderboard')
        .setDescription('Shows the server XP leaderboard'),

    async execute(interaction) {
        const users = await User.find({ guildId: interaction.guildId })
            .sort({ xp: -1 })
            .limit(10);

        if (!users.length) {
            return interaction.reply({
                content: 'No XP data found for this server.',
                ephemeral: true
            });
        }

        const leaderboardList = await Promise.all(users.map(async (user, index) => {
            const member = await interaction.guild.members.fetch(user.userId).catch(() => null);
            if (!member) return null;
            
            const level = Math.floor(Math.sqrt(user.xp / 100));
            return `${index + 1}. ${member.user.tag} - Level ${level} (${user.xp} XP)`;
        }));

        const embed = new EmbedBuilder()
            .setTitle('🏆 XP Leaderboard')
            .setDescription(leaderboardList.filter(entry => entry).join('\n'))
            .setColor('#2B2D31')
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter(true)}` });

        await interaction.reply({ embeds: [embed] });
    }
}; 