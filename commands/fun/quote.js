const { EmbedBuilder } = require('discord.js');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const NodeCache = require('node-cache');
const cache = new NodeCache({ stdTTL: 3600 }); // Cache for 1 hour

const categories = {
    inspirational: { emoji: '✨', color: '#FFD700' },
    motivational: { emoji: '💪', color: '#FF4500' },
    life: { emoji: '🌟', color: '#32CD32' },
    love: { emoji: '❤️', color: '#FF69B4' },
    wisdom: { emoji: '🧠', color: '#9370DB' },
    success: { emoji: '🏆', color: '#DAA520' },
    random: { emoji: '🎲', color: '#4169E1' }
};

module.exports = {
    name: 'quote',
    description: 'Get inspirational quotes by category or author',
    async execute(message, args) {
        let category = 'random';
        let author = '';

        // Parse arguments
        if (args.length) {
            if (args[0].startsWith('category:')) {
                category = args[0].split(':')[1].toLowerCase();
                author = args.slice(1).join(' ');
            } else {
                author = args.join(' ');
            }
        }

        if (category !== 'random' && !categories[category]) {
            const categoryList = Object.entries(categories)
                .map(([name, info]) => `${info.emoji} **${name}**`)
                .join('\n');
            return message.reply(`Invalid category! Available categories:\n${categoryList}`);
        }

        const rateCheck = await rateLimiter.checkLimit('quote');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        const cacheKey = `quote_${category}_${author}`;
        const cachedQuote = cache.get(cacheKey);

        if (cachedQuote) {
            message.channel.send({ embeds: [cachedQuote] });
            return;
        }

        try {
            const params = {
                category: category === 'random' ? undefined : category,
                author: author || undefined
            };

            const quote = await fetchAPI('quotes', '/random', { params });
            const { emoji, color } = categories[category] || categories.random;

            const embed = new EmbedBuilder()
                .setTitle(`${emoji} Quote of the Moment`)
                .setDescription(`*"${quote.content}"*`)
                .addFields([
                    { name: 'Author', value: quote.author || 'Unknown', inline: true },
                    { name: 'Category', value: quote.category || 'General', inline: true }
                ])
                .setColor(color)
                .setFooter({ 
                    text: `Tags: ${quote.tags?.join(', ') || 'None'} | Calls remaining: ${rateCheck.remaining}` 
                })
                .setTimestamp();

            if (quote.authorImage) {
                embed.setThumbnail(quote.authorImage);
            }

            cache.set(cacheKey, embed);
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            console.error('Quote Error:', error);
            message.reply('Failed to fetch quote. Please try again later.');
        }
    },
};
