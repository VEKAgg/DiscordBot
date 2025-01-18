const { EmbedBuilder } = require('discord.js');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');

module.exports = {
    name: 'catfact',
    description: 'Get a random cat fact with image',
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

            const embed = new EmbedBuilder()
                .setTitle('🐱 Cat Fact')
                .setDescription(fact.text)
                .setImage(image.url)
                .setFooter({ text: `Calls remaining: ${rateCheck.remaining} | Resets in: ${Math.ceil(rateCheck.resetIn / 60)}m` });

            message.channel.send({ embeds: [embed] });
        } catch (error) {
            message.reply('Failed to fetch cat fact. Please try again later.');
        }
    },
};
  