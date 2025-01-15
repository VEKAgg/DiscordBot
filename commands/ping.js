const { createEmbed } = require('../utils/embedUtils');

module.exports = {
    name: 'ping',
    description: 'Replies with Pong!',
    execute(message) {
        const embed = createEmbed('Ping Command', 'Pong!');
        message.channel.send({ embeds: [embed] });
    },
};
