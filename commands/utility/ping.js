const { SlashCommandBuilder, EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'ping',
    description: 'Check bot latency and API response time',
    category: 'utility',
    slashCommand: new SlashCommandBuilder()
        .setName('ping')
        .setDescription('Check bot latency and API response time'),

    async execute(interaction) {
        const isSlash = interaction.commandName !== undefined;
        
        try {
            const sent = isSlash 
                ? await interaction.deferReply({ fetchReply: true })
                : await interaction.channel.send('Pinging...');

            const roundtripLatency = sent.createdTimestamp - (isSlash ? interaction.createdTimestamp : interaction.createdAt);
            const wsLatency = interaction.client.ws.ping;

            const embed = new EmbedBuilder()
                .setTitle('🏓 Pong!')
                .setColor('#00ff00')
                .addFields([
                    { name: 'Bot Latency', value: `${roundtripLatency}ms`, inline: true },
                    { name: 'API Latency', value: `${wsLatency}ms`, inline: true }
                ])
                .setFooter({ text: 'Bot Status: Online' })
                .setTimestamp();

            const reply = { embeds: [embed] };
            if (isSlash) {
                await interaction.editReply(reply);
            } else {
                await sent.edit(reply);
            }
        } catch (error) {
            logger.error('Ping command error:', error);
            const reply = { 
                content: 'An error occurred while checking latency.',
                ephemeral: true 
            };
            if (isSlash) {
                await interaction.editReply(reply);
            } else {
                await interaction.reply(reply.content);
            }
        }
    }
};
