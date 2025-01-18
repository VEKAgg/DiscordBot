const { createEmbed } = require('../../utils/embedCreator');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const NodeCache = require('node-cache');
const { logger } = require('../../utils/logger');
const cache = new NodeCache({ stdTTL: 3600 }); // Cache for 1 hour

const categories = {
    today: { emoji: '📅', color: '#FF6B6B', description: 'Historical events that happened on this day' },
    science: { emoji: '🔬', color: '#4ECDC4', description: 'Scientific discoveries and phenomena' },
    history: { emoji: '📚', color: '#96CEB4', description: 'Historical events and figures' },
    space: { emoji: '🚀', color: '#6C5B7B', description: 'Space exploration and astronomy' },
    nature: { emoji: '🌿', color: '#2ECC71', description: 'Flora, fauna, and natural phenomena' },
    tech: { emoji: '💻', color: '#3498DB', description: 'Technology and innovation' },
    random: { emoji: '🎲', color: '#F1C40F', description: 'Random facts from all categories' }
};

module.exports = {
    name: 'fact',
    description: 'Get an interesting fact from various categories',
    contributor: 'Sleepless',
    async execute(message, args) {
        const category = args[0]?.toLowerCase();
        
        if (category && !categories[category]) {
            const categoryList = Object.entries(categories)
                .map(([name, info]) => `${info.emoji} **${name}** - ${info.description}`)
                .join('\n');
            return message.reply(`Invalid category! Available categories:\n${categoryList}`);
        }

        const rateCheck = await rateLimiter.checkLimit('fact');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        try {
            const fact = await fetchAPI('facts', category ? `/facts/${category}` : '/facts/random');
            const { emoji, color } = categories[category || 'random'];

            const embed = createEmbed({
                title: `${emoji} ${category ? category.charAt(0).toUpperCase() + category.slice(1) : 'Random'} Fact`,
                description: fact.text,
                color: color,
                fields: [
                    { name: 'Category', value: fact.category, inline: true },
                    { name: 'Source', value: fact.source || 'Unknown', inline: true },
                    { name: 'Verified', value: fact.verified ? '✅ Yes' : '❌ No', inline: true }
                ],
                author: {
                    name: message.author.tag,
                    iconURL: message.author.displayAvatarURL({ dynamic: true })
                },
                footer: {
                    text: `Contributor: ${module.exports.contributor} • VEKA | Resets in: ${Math.ceil(rateCheck.resetIn / 60)}m`,
                    iconURL: message.client.user.displayAvatarURL()
                }
            });

            if (fact.image_url) {
                embed.setImage(fact.image_url);
            }

            cache.set(category || 'random', embed);
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            logger.error('Fact Error:', error);
            message.reply('Failed to fetch fact. Please try again later.');
        }
    }
};
