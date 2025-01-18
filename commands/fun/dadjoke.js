const { EmbedBuilder } = require('discord.js');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const NodeCache = require('node-cache');
const cache = new NodeCache({ stdTTL: 1800 }); // Cache for 30 minutes

module.exports = {
    name: 'dadjoke',
    description: 'Send a random dad joke',
    async execute(message) {
        const cacheKey = 'dadjoke_latest';
        const cachedJoke = cache.get(cacheKey);

        if (cachedJoke) {
            message.channel.send({ embeds: [cachedJoke] });
            return;
        }

        const rateCheck = await rateLimiter.checkLimit('joke');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        try {
            const joke = await fetchAPI('joke', '/random', {
                headers: { 'Accept': 'application/json' }
            });

            const embed = new EmbedBuilder()
                .setTitle('👨 Dad Joke')
                .setDescription(joke.joke)
                .setColor('#FFD700')
                .setFooter({ text: `ID: ${joke.id} | Calls remaining: ${rateCheck.remaining}` })
                .setTimestamp();

            cache.set(cacheKey, embed);
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            message.reply('Failed to fetch a dad joke. Please try again later.');
        }
    },
};
