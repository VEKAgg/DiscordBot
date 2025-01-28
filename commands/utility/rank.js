const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');
const { User } = require('../../database');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'rank',
    description: 'Shows your or another user\'s rank',
    category: 'utility',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    slashCommand: new SlashCommandBuilder()
        .setName('rank')
        .setDescription('Shows rank information')
        .addUserOption(option =>
            option.setName('user')
                .setDescription('User to check rank for')
                .setRequired(false)),

    async execute(interaction) {
        const targetUser = interaction.options.getUser('user') || interaction.user;
        const userData = await User.findOne({ 
            userId: targetUser.id,
            guildId: interaction.guildId
        });

        if (!userData) {
            return interaction.reply({
                content: 'No rank data found for this user.',
                ephemeral: true
            });
        }

        const level = Math.floor(Math.sqrt(userData.xp / 100));
        const currentLevelXP = level * level * 100;
        const nextLevelXP = (level + 1) * (level + 1) * 100;
        const xpProgress = userData.xp - currentLevelXP;
        const xpNeeded = nextLevelXP - currentLevelXP;
        const progressPercentage = Math.round((xpProgress / xpNeeded) * 100);

        const embed = new EmbedBuilder()
            .setTitle(`${targetUser.tag}'s Rank`)
            .setThumbnail(targetUser.displayAvatarURL({ dynamic: true }))
            .setColor('#2B2D31')
            .addFields([
                { name: 'Level', value: level.toString(), inline: true },
                { name: 'XP', value: userData.xp.toString(), inline: true },
                { name: 'Progress to Next Level', value: `${progressPercentage}%`, inline: true }
            ])
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await interaction.reply({ embeds: [embed] });
    }
}; 