const { createEmbed } = require('../../utils/embedCreator');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const { logger } = require('../../utils/logger');

module.exports = {
    name: 'catfact',
    description: 'Get a random cat fact with image',
    contributor: 'Sleepless',
    async execute(message) {
        const rateCheck = await rateLimiter.checkLimit('cat');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        try {
            const [fact, image] = await Promise.all([
                fetchAPI('cat', '/facts/random'),
                fetchAPI('cat', '/images/random')
            ]);

            const embed = createEmbed({
                title: '🐱 Cat Fact',
                description: fact.text,
                image: { url: image.url },
                author: {
                    name: message.author.tag,
                    iconURL: message.author.displayAvatarURL({ dynamic: true })
                },
                footer: {
                    text: `Contributor: ${module.exports.contributor} • VEKA | Resets in: ${Math.ceil(rateCheck.resetIn / 60)}m`,
                    iconURL: message.client.user.displayAvatarURL()
                }
            });

            message.channel.send({ embeds: [embed] });
        } catch (error) {
            logger.error('Cat fact Error:', error);
            message.reply('Failed to fetch cat fact. Please try again later.');
        }
    },
};
  