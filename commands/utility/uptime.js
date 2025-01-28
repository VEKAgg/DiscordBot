const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');
const { formatTime } = require('../../utils/formatters');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'uptime',
    description: 'Shows bot uptime',
    category: 'utility',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    slashCommand: new SlashCommandBuilder()
        .setName('uptime')
        .setDescription('Shows how long the bot has been online'),

    async execute(interaction) {
        const uptime = formatTime(process.uptime() * 1000);

        const embed = new EmbedBuilder()
            .setTitle('Bot Uptime')
            .setColor('#2B2D31')
            .setDescription(`I have been online for ${uptime}`)
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await interaction.reply({ embeds: [embed] });
    }
};
