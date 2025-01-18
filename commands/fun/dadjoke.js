const { createEmbed } = require('../../utils/embedCreator');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const NodeCache = require('node-cache');
const { logger } = require('../../utils/logger');
const cache = new NodeCache({ stdTTL: 1800 }); // Cache for 30 minutes

module.exports = {
    name: 'dadjoke',
    description: 'Send a random dad joke',
    contributor: 'Sleepless',
    async execute(message) {
        const rateCheck = await rateLimiter.checkLimit('joke');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        try {
            const joke = await fetchAPI('joke', '/random', {
                headers: { 'Accept': 'application/json' }
            });

            const embed = createEmbed({
                title: '👨 Dad Joke',
                description: joke.joke,
                color: '#FFD700',
                author: {
                    name: message.author.tag,
                    iconURL: message.author.displayAvatarURL({ dynamic: true })
                },
                footer: {
                    text: `Contributor: ${module.exports.contributor} • VEKA | ID: ${joke.id} | Resets in: ${Math.ceil(rateCheck.resetIn / 60)}m`,
                    iconURL: message.client.user.displayAvatarURL()
                }
            });

            cache.set('dadjoke_latest', embed);
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            logger.error('Dad joke Error:', error);
            message.reply('Failed to fetch a dad joke. Please try again later.');
        }
    },
};
