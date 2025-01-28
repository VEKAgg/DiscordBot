const { createEmbed } = require('../../utils/embedCreator');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const NodeCache = require('node-cache');
const { logger } = require('../../utils/logger');
const cache = new NodeCache({ stdTTL: 1800 }); // Cache for 30 minutes

const animals = {
    cat: {
        emoji: '🐱',
        color: '#FFB6C1',
        description: 'Fascinating feline facts',
        breeds: true
    },
    dog: {
        emoji: '🐶',
        color: '#8B4513',
        description: 'Delightful canine facts',
        breeds: true
    },
    panda: {
        emoji: '🐼',
        color: '#000000',
        description: 'Peaceful panda facts',
        breeds: false
    },
    fox: {
        emoji: '🦊',
        color: '#FFA500',
        description: 'Fantastic fox facts',
        breeds: false
    },
    koala: {
        emoji: '🐨',
        color: '#808080',
        description: 'Cuddly koala facts',
        breeds: false
    }
};

module.exports = {
    name: 'animalfact',
    aliases: ['catfact', 'dogfact'],
    description: 'Get random animal facts with images',
    contributor: 'Sleepless',
    async execute(message, args) {
        let animal = args[0]?.toLowerCase() || 
            (message.content.includes('catfact') ? 'cat' : 
             message.content.includes('dogfact') ? 'dog' : 'random');

        if (animal === 'random') {
            animal = Object.keys(animals)[Math.floor(Math.random() * Object.keys(animals).length)];
        }

        if (!animals[animal]) {
            const animalList = Object.entries(animals)
                .map(([name, info]) => `${info.emoji} **${name}** - ${info.description}`)
                .join('\n');
            return message.reply(`Invalid animal! Available options:\n${animalList}`);
        }

        const rateCheck = await rateLimiter.checkLimit('animal');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        try {
            const [fact, image] = await Promise.all([
                fetchAPI(animal, '/facts/random'),
                fetchAPI(animal, '/images/random')
            ]);

            const { emoji, color } = animals[animal];
            const embed = createEmbed({
                title: `${emoji} ${animal.charAt(0).toUpperCase() + animal.slice(1)} Fact`,
                description: animal === 'dog' ? fact.facts[0] : fact.text,
                image: { url: image.url },
                color: color,
                author: {
                    name: message.author.tag,
                    iconURL: message.author.displayAvatarURL({ dynamic: true })
                },
                footer: {
                    text: `Contributor: ${module.exports.contributor} • VEKA | Resets in: ${Math.ceil(rateCheck.resetIn / 60)}m`,
                    iconURL: message.client.user.displayAvatarURL()
                }
            });

            if (image.breeds?.length) {
                embed.addFields({
                    name: 'Breed Information',
                    value: formatBreedInfo(image.breeds[0]),
                    inline: false
                });
            }

            cache.set(`animalfact_${animal}`, embed);
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            logger.error(`${animal} fact Error:`, error);
            message.reply(`Failed to fetch ${animal} fact. Please try again later.`);
        }
    }
};

function formatBreedInfo(breed) {
    if (!breed) return 'No breed information available';
    
    const info = [];
    if (breed.name) info.push(`**Breed:** ${breed.name}`);
    if (breed.temperament) info.push(`**Temperament:** ${breed.temperament}`);
    if (breed.life_span) info.push(`**Life Span:** ${breed.life_span}`);
    if (breed.weight?.metric) info.push(`**Weight:** ${breed.weight.metric} kg`);
    if (breed.height?.metric) info.push(`**Height:** ${breed.height.metric} cm`);
    
    return info.length ? info.join('\n') : 'No breed information available';
} 