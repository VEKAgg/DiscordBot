const { createEmbed } = require('../../utils/embedUtils');

module.exports = {
    name: 'ping',
    description: 'Replies with Pong!',
    execute(message) {
        const embed = createEmbed('Pong!', `Latency is ${Date.now() - message.createdTimestamp}ms.`);
        message.channel.send({ embeds: [embed] });
    },
};
