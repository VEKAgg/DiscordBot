const { EmbedBuilder } = require('discord.js');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const NodeCache = require('node-cache');
const cache = new NodeCache({ stdTTL: 300 }); // Cache for 5 minutes

module.exports = {
    name: 'gif',
    description: 'Search for a GIF',
    async execute(message, args) {
        if (!args.length) {
            return message.reply('Please provide a search term. Example: `#gif cute cats`');
        }

        const query = args.join(' ');
        const cacheKey = `gif_${query.toLowerCase()}`;
        const cachedGif = cache.get(cacheKey);

        if (cachedGif) {
            message.channel.send({ embeds: [cachedGif] });
            return;
        }

        const rateCheck = await rateLimiter.checkLimit('giphy');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        try {
            const response = await fetchAPI('giphy', '/v1/gifs/search', {
                params: {
                    q: query,
                    limit: 10,
                    rating: 'g'
                }
            });

            if (!response.data.length) {
                return message.reply('No GIFs found for that search term.');
            }

            const randomGif = response.data[Math.floor(Math.random() * response.data.length)];
            const embed = new EmbedBuilder()
                .setTitle(`🎬 GIF Search: ${query}`)
                .setImage(randomGif.images.original.url)
                .setColor('#00ff00')
                .setFooter({ text: `Powered by GIPHY | Calls remaining: ${rateCheck.remaining}` })
                .setTimestamp();

            cache.set(cacheKey, embed);
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            console.error('GIF API Error:', error);
            message.reply('Failed to fetch GIF. Please try again later.');
        }
    },
}; 