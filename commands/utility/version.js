const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');
const { version } = require('../../package.json');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'version',
    description: 'Shows current bot version',
    category: 'utility',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    slashCommand: new SlashCommandBuilder()
        .setName('version')
        .setDescription('Shows current bot version'),

    async execute(interaction) {
        const embed = new EmbedBuilder()
            .setTitle('Bot Version')
            .setColor('#2B2D31')
            .setDescription(`Current version: v${version}`)
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await interaction.reply({ embeds: [embed] });
    }
}; 