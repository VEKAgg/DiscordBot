const { EmbedBuilder } = require('discord.js');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');

module.exports = {
    name: 'dogfact',
    description: 'Get a random dog fact with image',
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

            const embed = new EmbedBuilder()
                .setTitle('🐶 Dog Fact')
                .setDescription(fact.facts[0])
                .setImage(image.url)
                .setColor('#8B4513')
                .setFooter({ text: `Calls remaining: ${rateCheck.remaining} | Resets in: ${Math.ceil(rateCheck.resetIn / 60)}m` });

            message.channel.send({ embeds: [embed] });
        } catch (error) {
            message.reply('Failed to fetch dog fact. Please try again later.');
        }
    },
};
  