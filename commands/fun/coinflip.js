const { EmbedBuilder } = require('discord.js');
const NodeCache = require('node-cache');
const cache = new NodeCache({ stdTTL: 86400 }); // Cache for 24 hours

module.exports = {
    name: 'coinflip',
    description: 'Flip a coin with statistics tracking',
    async execute(message) {
        const userId = message.author.id;
        const statsKey = `coinflip_stats_${userId}`;
        
        // Get or initialize user stats
        let stats = cache.get(statsKey) || { heads: 0, tails: 0 };
        
        // Flip animation
        const loadingEmbed = new EmbedBuilder()
            .setTitle('🎲 Flipping Coin')
            .setDescription('The coin spins in the air...')
            .setColor('#FFD700')
            .setFooter({ text: 'Watching the coin flip...' });
            
        const msg = await message.channel.send({ embeds: [loadingEmbed] });
        
        // Wait for dramatic effect
        await new Promise(resolve => setTimeout(resolve, 1500));
        
        // Determine result
        const result = Math.random() < 0.5 ? 'Heads' : 'Tails';
        result === 'Heads' ? stats.heads++ : stats.tails++;
        
        // Update stats
        cache.set(statsKey, stats);
        
        // Calculate percentages
        const total = stats.heads + stats.tails;
        const headsPercent = ((stats.heads / total) * 100).toFixed(1);
        const tailsPercent = ((stats.tails / total) * 100).toFixed(1);
        
        const resultEmbed = new EmbedBuilder()
            .setTitle(`🪙 Coin Flip Result: ${result}`)
            .setDescription(`${result === 'Heads' ? '👑' : '🦅'} The coin landed on **${result}**!`)
            .addFields([
                { 
                    name: 'Your Flip History', 
                    value: `Heads: ${stats.heads} (${headsPercent}%)\nTails: ${stats.tails} (${tailsPercent}%)`,
                    inline: true 
                },
                { 
                    name: 'Total Flips', 
                    value: `${total} flips`,
                    inline: true 
                },
                {
                    name: 'Streak Potential',
                    value: getStreakComment(result === 'Heads' ? headsPercent : tailsPercent),
                    inline: false
                }
            ])
            .setColor(result === 'Heads' ? '#FFD700' : '#C0C0C0')
            .setFooter({ text: `Flipped by ${message.author.tag}` })
            .setTimestamp();

        msg.edit({ embeds: [resultEmbed] });
    },
};

function getStreakComment(percentage) {
    if (percentage > 75) return '🔥 You\'re on fire with ' + (percentage > 50 ? 'heads' : 'tails') + '!';
    if (percentage > 60) return '📈 Looking good!';
    if (percentage > 40) return '⚖️ Pretty balanced flips!';
    return '🎲 Keep flipping to build your streak!';
}
