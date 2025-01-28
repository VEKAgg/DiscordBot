const { createEmbed } = require('../../utils/embedCreator');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const { logger } = require('../../utils/logger');

module.exports = {
    name: 'gif',
    description: 'Search for a GIF or get a random one',
    contributor: 'Sleepless',
    async execute(message, args) {
        const query = args.join(' ');
        const rateCheck = await rateLimiter.checkLimit('gif');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        try {
            const gif = await fetchAPI('giphy', query ? '/search' : '/random', {
                params: query ? { q: query, limit: 1 } : {}
            });

            const gifData = query ? gif.data[0] : gif.data;
            if (!gifData) {
                return message.reply('No GIF found for that search term!');
            }

            const embed = createEmbed({
                title: '🎬 GIF',
                description: query ? `Search: "${query}"` : 'Random GIF',
                image: { url: gifData.images.original.url },
                color: '#FF69B4',
                author: {
                    name: message.author.tag,
                    iconURL: message.author.displayAvatarURL({ dynamic: true })
                },
                footer: {
                    text: `Contributor: ${module.exports.contributor} • VEKA | Powered by GIPHY`,
                    iconURL: message.client.user.displayAvatarURL()
                }
            });

            message.channel.send({ embeds: [embed] });
        } catch (error) {
            logger.error('GIF Error:', error);
            message.reply('Failed to fetch GIF. Please try again later.');
        }
    },
}; 