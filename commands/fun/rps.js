const { EmbedBuilder } = require('discord.js');
const NodeCache = require('node-cache');
const cache = new NodeCache({ stdTTL: 86400 }); // Cache for 24 hours

module.exports = {
    name: 'rps',
    description: 'Play Rock, Paper, Scissors against the bot',
    execute(message, args) {
        const choices = ['rock', 'paper', 'scissors'];
        const emojis = { rock: '🪨', paper: '📄', scissors: '✂️' };
        const userChoice = args[0]?.toLowerCase();

        if (!choices.includes(userChoice)) {
            return message.reply('Invalid choice! Please use `#rps rock`, `#rps paper`, or `#rps scissors`');
        }

        const botChoice = choices[Math.floor(Math.random() * choices.length)];
        const userId = message.author.id;
        const statsKey = `rps_stats_${userId}`;
        
        // Get or initialize user stats
        let stats = cache.get(statsKey) || { wins: 0, losses: 0, ties: 0 };

        // Determine winner
        let result, color, resultEmoji;
        if (userChoice === botChoice) {
            result = 'It\'s a tie!';
            color = '#FFD700';
            resultEmoji = '🤝';
            stats.ties++;
        } else if (
            (userChoice === 'rock' && botChoice === 'scissors') ||
            (userChoice === 'paper' && botChoice === 'rock') ||
            (userChoice === 'scissors' && botChoice === 'paper')
        ) {
            result = 'You win!';
            color = '#00FF00';
            resultEmoji = '🎉';
            stats.wins++;
        } else {
            result = 'I win!';
            color = '#FF0000';
            resultEmoji = '😈';
            stats.losses++;
        }

        // Update stats in cache
        cache.set(statsKey, stats);

        // Calculate win rate
        const totalGames = stats.wins + stats.losses + stats.ties;
        const winRate = ((stats.wins / totalGames) * 100).toFixed(1);

        const embed = new EmbedBuilder()
            .setTitle('🎮 Rock, Paper, Scissors')
            .setDescription(`${message.author} chose ${emojis[userChoice]} vs my ${emojis[botChoice]}`)
            .addFields([
                { name: 'Result', value: `${resultEmoji} ${result}`, inline: false },
                { name: 'Your Stats', value: 
                    `Wins: ${stats.wins} 🏆\n` +
                    `Losses: ${stats.losses} 💔\n` +
                    `Ties: ${stats.ties} 🤝\n` +
                    `Win Rate: ${winRate}% 📊`, 
                    inline: true 
                },
                { name: 'Game Rules', value: 
                    '🪨 Rock crushes Scissors\n' +
                    '📄 Paper covers Rock\n' +
                    '✂️ Scissors cuts Paper', 
                    inline: true 
                }
            ])
            .setColor(color)
            .setFooter({ text: 'Play again with #rps [choice]' })
            .setTimestamp();

        message.channel.send({ embeds: [embed] });
    },
};
  