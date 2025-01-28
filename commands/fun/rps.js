const { createEmbed } = require('../../utils/embedCreator');
const NodeCache = require('node-cache');
const { logger } = require('../../utils/logger');
const cache = new NodeCache({ stdTTL: 86400 }); // Cache for 24 hours

const choices = {
    rock: { emoji: '🪨', beats: 'scissors', description: 'Rock crushes Scissors' },
    paper: { emoji: '📄', beats: 'rock', description: 'Paper covers Rock' },
    scissors: { emoji: '✂️', beats: 'paper', description: 'Scissors cuts Paper' }
};

module.exports = {
    name: 'rps',
    description: 'Play Rock, Paper, Scissors against the bot',
    contributor: 'Sleepless',
    execute(message, args) {
        const userChoice = args[0]?.toLowerCase();

        if (!choices[userChoice]) {
            return message.reply('Invalid choice! Please use `#rps rock`, `#rps paper`, or `#rps scissors`');
        }

        const botChoice = Object.keys(choices)[Math.floor(Math.random() * 3)];
        let result, color;

        if (userChoice === botChoice) {
            result = "It's a tie! 🤝";
            color = '#FFD700';
        } else if (choices[userChoice].beats === botChoice) {
            result = 'You win! 🎉';
            color = '#00FF00';
        } else {
            result = 'Bot wins! 🤖';
            color = '#FF0000';
        }

        // Update stats in cache
        const stats = cache.get('rps_stats') || { wins: 0, losses: 0, ties: 0 };
        if (result.includes('win')) stats.wins++;
        else if (result.includes('Bot')) stats.losses++;
        else stats.ties++;
        cache.set('rps_stats', stats);

        const embed = createEmbed({
            title: '🎮 Rock, Paper, Scissors',
            description: result,
            color: color,
            fields: [
                { 
                    name: 'Your Choice', 
                    value: `${choices[userChoice].emoji} ${userChoice.charAt(0).toUpperCase() + userChoice.slice(1)}`,
                    inline: true 
                },
                { 
                    name: 'Bot Choice', 
                    value: `${choices[botChoice].emoji} ${botChoice.charAt(0).toUpperCase() + botChoice.slice(1)}`,
                    inline: true 
                },
                { 
                    name: 'Stats', 
                    value: `Wins: ${stats.wins} | Losses: ${stats.losses} | Ties: ${stats.ties}`,
                    inline: false 
                },
                { 
                    name: 'Game Rules', 
                    value: Object.values(choices).map(c => `${c.emoji} ${c.description}`).join('\n'),
                    inline: false 
                }
            ],
            author: {
                name: message.author.tag,
                iconURL: message.author.displayAvatarURL({ dynamic: true })
            },
            footer: {
                text: `Contributor: ${module.exports.contributor} • VEKA | Play again with #rps [choice]`,
                iconURL: message.client.user.displayAvatarURL()
            }
        });

        message.channel.send({ embeds: [embed] });
    }
};