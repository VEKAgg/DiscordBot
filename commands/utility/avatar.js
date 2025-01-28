const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'avatar',
    description: 'Shows user avatar',
    category: 'utility',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    slashCommand: new SlashCommandBuilder()
        .setName('avatar')
        .setDescription('Shows user avatar')
        .addUserOption(option =>
            option.setName('user')
                .setDescription('User to show avatar for')
                .setRequired(false)),

    async execute(interaction) {
        const targetUser = interaction.options.getUser('user') || interaction.user;

        const embed = new EmbedBuilder()
            .setTitle(`${targetUser.tag}'s Avatar`)
            .setColor('#2B2D31')
            .setImage(targetUser.displayAvatarURL({ size: 4096, dynamic: true }))
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await interaction.reply({ embeds: [embed] });
    }
};