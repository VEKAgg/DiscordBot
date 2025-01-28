const { createEmbed } = require('../../utils/embedCreator');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const NodeCache = require('node-cache');
const { logger } = require('../../utils/logger');
const cache = new NodeCache({ stdTTL: 3600 }); // Cache for 1 hour

const categories = {
    inspire: { emoji: '✨', color: '#FFD700', description: 'Inspirational quotes' },
    life: { emoji: '🌟', color: '#98FB98', description: 'Life wisdom' },
    love: { emoji: '❤️', color: '#FF69B4', description: 'Love and relationships' },
    success: { emoji: '🎯', color: '#4169E1', description: 'Success and motivation' },
    random: { emoji: '🎲', color: '#DDA0DD', description: 'Random quotes' }
};

module.exports = {
    name: 'quote',
    description: 'Get an inspiring quote',
    contributor: 'Sleepless',
    async execute(message, args) {
        const category = args[0]?.toLowerCase();
        
        if (category && !categories[category]) {
            const categoryList = Object.entries(categories)
                .map(([name, info]) => `${info.emoji} **${name}** - ${info.description}`)
                .join('\n');
            return message.reply(`Invalid category! Available categories:\n${categoryList}`);
        }

        const rateCheck = await rateLimiter.checkLimit('quote');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        try {
            const quote = await fetchAPI('quotes', category ? `/quotes/${category}` : '/quotes/random');
            const { emoji, color } = categories[category || 'random'];

            const embed = createEmbed({
                title: `${emoji} Quote of the Moment`,
                description: `*"${quote.text}"*\n\n— ${quote.author || 'Unknown'}`,
                color: color,
                author: {
                    name: message.author.tag,
                    iconURL: message.author.displayAvatarURL({ dynamic: true })
                },
                footer: {
                    text: `Contributor: ${module.exports.contributor} • VEKA | Category: ${category || 'Random'}`,
                    iconURL: message.client.user.displayAvatarURL()
                }
            });

            cache.set(`quote_${category || 'random'}`, embed);
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            logger.error('Quote Error:', error);
            message.reply('Failed to fetch quote. Please try again later.');
        }
    }
};
