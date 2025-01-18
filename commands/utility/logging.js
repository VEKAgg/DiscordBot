const embedUtils = require('../../utils/embedUtils');

module.exports = {
    name: 'logging',
    description: 'Set a channel for logging activities.',
    execute(message, args, client) {
        const channel = message.mentions.channels.first();

        if (!channel) {
            const embed = createEmbed(
                'Error',
                'Please mention a channel to set as the logging channel.',
                0xFF0000
            ); // Red for error
            return message.channel.send({ embeds: [embed] });
        }

        client.loggingChannel = channel.id;

        const embed = createEmbed(
            'Logging Enabled',
            `Logging has been enabled for <#${channel.id}>.`
        );
        message.channel.send({ embeds: [embed] });
    },
};
