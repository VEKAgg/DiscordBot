const { EmbedBuilder } = require('discord.js');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');

const zodiacEmojis = {
    aries: '♈',
    taurus: '♉',
    gemini: '♊',
    cancer: '♋',
    leo: '♌',
    virgo: '♍',
    libra: '♎',
    scorpio: '♏',
    sagittarius: '♐',
    capricorn: '♑',
    aquarius: '♒',
    pisces: '♓'
};

const zodiacElements = {
    aries: { element: 'Fire 🔥', quality: 'Cardinal', ruler: 'Mars ♂️' },
    taurus: { element: 'Earth 🌍', quality: 'Fixed', ruler: 'Venus ♀️' },
    gemini: { element: 'Air 💨', quality: 'Mutable', ruler: 'Mercury ☿' },
    cancer: { element: 'Water 💧', quality: 'Cardinal', ruler: 'Moon 🌙' },
    leo: { element: 'Fire 🔥', quality: 'Fixed', ruler: 'Sun ☀️' },
    virgo: { element: 'Earth 🌍', quality: 'Mutable', ruler: 'Mercury ☿' },
    libra: { element: 'Air 💨', quality: 'Cardinal', ruler: 'Venus ♀️' },
    scorpio: { element: 'Water 💧', quality: 'Fixed', ruler: 'Pluto ♇' },
    sagittarius: { element: 'Fire 🔥', quality: 'Mutable', ruler: 'Jupiter ♃' },
    capricorn: { element: 'Earth 🌍', quality: 'Cardinal', ruler: 'Saturn ♄' },
    aquarius: { element: 'Air 💨', quality: 'Fixed', ruler: 'Uranus ⛢' },
    pisces: { element: 'Water 💧', quality: 'Mutable', ruler: 'Neptune ♆' }
};

module.exports = {
    name: 'horoscope',
    description: 'Get your daily horoscope reading',
    async execute(message, args) {
        if (!args[0]) {
            return message.reply('Please provide a zodiac sign. Example: `#horoscope aries`');
        }

        const sign = args[0].toLowerCase();
        if (!zodiacEmojis[sign]) {
            const validSigns = Object.keys(zodiacEmojis).map(s => `${zodiacEmojis[s]} ${s}`).join('\n');
            return message.reply(`Invalid zodiac sign! Valid signs are:\n${validSigns}`);
        }

        const rateCheck = await rateLimiter.checkLimit('horoscope');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        try {
            const horoscope = await fetchAPI('horoscope', `/daily/${sign}`);
            const signInfo = zodiacElements[sign];
            
            const embed = new EmbedBuilder()
                .setTitle(`${zodiacEmojis[sign]} Daily Horoscope: ${sign.charAt(0).toUpperCase() + sign.slice(1)}`)
                .setDescription(horoscope.horoscope)
                .addFields([
                    { 
                        name: 'Sign Information',
                        value: `Element: ${signInfo.element}\nQuality: ${signInfo.quality}\nRuling Planet: ${signInfo.ruler}`,
                        inline: true
                    },
                    {
                        name: 'Daily Aspects',
                        value: `Lucky Number: ${horoscope.lucky_number} 🎲\nMood: ${horoscope.mood} 😊\nColor: ${horoscope.color} 🎨`,
                        inline: true
                    },
                    {
                        name: 'Compatibility',
                        value: getCompatibleSigns(sign),
                        inline: false
                    }
                ])
                .setColor(getZodiacColor(sign))
                .setFooter({ text: `Updated: ${horoscope.date} | Calls remaining: ${rateCheck.remaining}` })
                .setTimestamp();

            message.channel.send({ embeds: [embed] });
        } catch (error) {
            console.error('Horoscope Error:', error);
            message.reply('Failed to fetch horoscope. Please try again later.');
        }
    },
};

function getZodiacColor(sign) {
    const colors = {
        aries: '#FF0000',
        taurus: '#00FF00',
        gemini: '#FFFF00',
        cancer: '#SILVER',
        leo: '#FFD700',
        virgo: '#964B00',
        libra: '#FFC0CB',
        scorpio: '#800000',
        sagittarius: '#800080',
        capricorn: '#000000',
        aquarius: '#0000FF',
        pisces: '#40E0D0'
    };
    return colors[sign];
}

function getCompatibleSigns(sign) {
    const compatibility = {
        aries: ['leo', 'sagittarius', 'gemini', 'aquarius'],
        taurus: ['virgo', 'capricorn', 'cancer', 'pisces'],
        gemini: ['libra', 'aquarius', 'aries', 'leo'],
        cancer: ['scorpio', 'pisces', 'taurus', 'virgo'],
        leo: ['aries', 'sagittarius', 'gemini', 'libra'],
        virgo: ['taurus', 'capricorn', 'cancer', 'scorpio'],
        libra: ['gemini', 'aquarius', 'leo', 'sagittarius'],
        scorpio: ['cancer', 'pisces', 'virgo', 'capricorn'],
        sagittarius: ['aries', 'leo', 'libra', 'aquarius'],
        capricorn: ['taurus', 'virgo', 'scorpio', 'pisces'],
        aquarius: ['gemini', 'libra', 'aries', 'sagittarius'],
        pisces: ['cancer', 'scorpio', 'taurus', 'capricorn']
    };
    
    const matches = compatibility[sign].map(s => `${zodiacEmojis[s]} ${s}`);
    return `Best matches:\n${matches.join('\n')}`;
}
