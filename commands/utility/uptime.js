const embedUtils = require('../../utils/embedUtils');

module.exports = {
    name: 'uptime',
    description: 'Check the bot\'s uptime.',
    execute(message) {
        const totalSeconds = Math.floor(message.client.uptime / 1000);
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;

        const embed = createEmbed({
            title: 'Uptime',
            description: `The bot has been online for **${hours}h ${minutes}m ${seconds}s**.`,
            color: 'BLUE',
            message,
        });

        message.channel.send({ embeds: [embed] });
    },
};
