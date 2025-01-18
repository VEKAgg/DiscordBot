const { createEmbed } = require('../../utils/embedCreator');

module.exports = {
    name: 'ping',
    description: 'Responds with bot latency.',
    async execute(message) {
        try {
            if (!message || !message.author || message.author.bot) return; // Ignore bot messages

            // Send initial response
            const sent = await message.channel.send('Pinging...');

            // Create an embed with the latency info
            const pingEmbed = createEmbed({
                title: '🏓 Pong!',
                description: `Latency: **${sent.createdTimestamp - message.createdTimestamp}ms**\nAPI Latency: **${Math.round(message.client.ws.ping)}ms**`,
            });

            // Edit the message with the embed
            await sent.edit({ content: null, embeds: [pingEmbed] });
        } catch (error) {
            console.error('Error in ping command:', error);
        }
    },
};
