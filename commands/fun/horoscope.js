const { createEmbed } = require('../../utils/embedCreator');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const NodeCache = require('node-cache');
const { logger } = require('../../utils/logger');
const cache = new NodeCache({ stdTTL: 43200 }); // Cache for 12 hours

const signs = {
    aries: { emoji: '♈', color: '#FF0000', description: 'March 21 - April 19' },
    taurus: { emoji: '♉', color: '#00FF00', description: 'April 20 - May 20' },
    gemini: { emoji: '♊', color: '#FFFF00', description: 'May 21 - June 20' },
    cancer: { emoji: '♋', color: '#FFFFFF', description: 'June 21 - July 22' },
    leo: { emoji: '♌', color: '#FFA500', description: 'July 23 - August 22' },
    virgo: { emoji: '♍', color: '#964B00', description: 'August 23 - September 22' },
    libra: { emoji: '♎', color: '#FFC0CB', description: 'September 23 - October 22' },
    scorpio: { emoji: '♏', color: '#800000', description: 'October 23 - November 21' },
    sagittarius: { emoji: '♐', color: '#800080', description: 'November 22 - December 21' },
    capricorn: { emoji: '♑', color: '#000000', description: 'December 22 - January 19' },
    aquarius: { emoji: '♒', color: '#0000FF', description: 'January 20 - February 18' },
    pisces: { emoji: '♓', color: '#008080', description: 'February 19 - March 20' }
};

module.exports = {
    name: 'horoscope',
    description: 'Get your daily horoscope',
    contributor: 'Sleepless',
    async execute(message, args) {
        const sign = args[0]?.toLowerCase();

        if (!sign || !signs[sign]) {
            const signList = Object.entries(signs)
                .map(([name, info]) => `${info.emoji} **${name}** - ${info.description}`)
                .join('\n');
            return message.reply(`Please specify a zodiac sign!\n${signList}`);
        }

        const rateCheck = await rateLimiter.checkLimit('horoscope');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        try {
            const horoscope = await fetchAPI('horoscope', `/daily/${sign}`);
            const { emoji, color } = signs[sign];

            const embed = createEmbed({
                title: `${emoji} ${sign.charAt(0).toUpperCase() + sign.slice(1)}'s Horoscope`,
                description: horoscope.prediction,
                color: color,
                fields: [
                    { name: 'Date Range', value: signs[sign].description, inline: true },
                    { name: 'Lucky Number', value: horoscope.lucky_number.toString(), inline: true },
                    { name: 'Mood', value: horoscope.mood, inline: true },
                    { name: 'Compatibility', value: horoscope.compatibility || 'N/A', inline: true }
                ],
                author: {
                    name: message.author.tag,
                    iconURL: message.author.displayAvatarURL({ dynamic: true })
                },
                footer: {
                    text: `Contributor: ${module.exports.contributor} • VEKA | Date: ${new Date().toLocaleDateString()}`,
                    iconURL: message.client.user.displayAvatarURL()
                }
            });

            cache.set(`horoscope_${sign}`, embed);
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            logger.error('Horoscope Error:', error);
            message.reply('Failed to fetch horoscope. Please try again later.');
        }
    }
};
