const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'ping',
    description: 'Check bot latency',
    category: 'utility',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    slashCommand: new SlashCommandBuilder()
        .setName('ping')
        .setDescription('Check bot latency'),

    async execute(interaction) {
        const sent = await interaction.reply({ 
            content: 'Pinging...', 
            fetchReply: true 
        });

        const embed = new EmbedBuilder()
            .setTitle('🏓 Pong!')
            .setColor('#2B2D31')
            .addFields([
                { name: 'Latency', value: `${sent.createdTimestamp - interaction.createdTimestamp}ms`, inline: true },
                { name: 'API Latency', value: `${Math.round(interaction.client.ws.ping)}ms`, inline: true }
            ])
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await interaction.editReply({ content: null, embeds: [embed] });
    }
};
