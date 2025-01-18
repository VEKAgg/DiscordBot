const { EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'leaderboard',
    description: 'Show the gaming leaderboard',
    execute(message) {
        const embed = new EmbedBuilder()
            .setTitle('🎮 Gaming Leaderboard')
            .setDescription('Top players and their scores')
            .setColor('#0099ff')
            .setTimestamp();
            
        // Add your leaderboard logic here
        
        message.channel.send({ embeds: [embed] });
    },
};
