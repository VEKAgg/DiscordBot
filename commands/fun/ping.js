const embedUtils = require('../../utils/embedUtils');

module.exports = {
    name: 'ping',
    description: 'Check the bot\'s latency.',
    execute(message) {
        const latency = Date.now() - message.createdTimestamp;
        const apiLatency = Math.round(message.client.ws.ping);

        const embed = createEmbed({
            title: 'Pong!',
            description: `Latency: **${latency}ms**\nAPI Latency: **${apiLatency}ms**`,
            color: 'GREEN',
            message,
        });

        message.channel.send({ embeds: [embed] });
    },
};
