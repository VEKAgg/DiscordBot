const { createEmbed } = require('../../utils/embedCreator');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const { logger } = require('../../utils/logger');

module.exports = {
    name: 'dogfact',
    description: 'Get a random dog fact with image',
    contributor: 'Sleepless',
    async execute(message) {
        const rateCheck = await rateLimiter.checkLimit('dog');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        try {
            const [fact, image] = await Promise.all([
                fetchAPI('dog', '/facts/random'),
                fetchAPI('dog', '/images/random')
            ]);

            const embed = createEmbed({
                title: '🐶 Dog Fact',
                description: fact.facts[0],
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
            logger.error('Dog fact command error:', error);
            message.reply('Failed to fetch dog fact. Please try again later.');
        }
    },
};
  