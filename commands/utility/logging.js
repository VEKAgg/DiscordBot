const { createEmbed } = require('../../utils/embedCreator');
const { logger } = require('../../utils/logger');

module.exports = {
    name: 'logging',
    description: 'Set a channel for logging activities.',
    execute(message, args, client) {
        try {
            const channel = message.mentions.channels.first();

            if (!channel) {
                const embed = createEmbed({
                    title: 'Error',
                    description: 'Please mention a channel to set as the logging channel.',
                    color: 0xFF0000
                });
                return message.channel.send({ embeds: [embed] });
            }

            client.loggingChannel = channel.id;
            logger.info(`Logging channel set to: ${channel.name} (${channel.id})`);

            const embed = createEmbed({
                title: 'Logging Enabled',
                description: `Logging has been enabled for <#${channel.id}>.`
            });
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            logger.error('Error in logging command:', error);
            message.reply('An error occurred while setting up logging.');
        }
    },
};
