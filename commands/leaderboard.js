const { createEmbed } = require('../utils/embedUtils');

module.exports = {
    name: 'leaderboard',
    description: 'Displays the points leaderboard.',
    execute(message, args, client) {
        const sorted = Array.from(client.points.entries())
            .sort(([, a], [, b]) => b - a)
            .slice(0, 10)
            .map(([userId, points], index) => `${index + 1}. <@${userId}>: ${points} points`)
            .join('\n');

        const embed = createEmbed('Points Leaderboard', sorted || 'No points yet!');
        message.channel.send({ embeds: [embed] });
    },
};
