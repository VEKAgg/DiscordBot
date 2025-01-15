const { createEmbed } = require('../utils/embedUtils');

module.exports = {
    name: 'gaming-leaderboard',
    description: 'Displays the gaming leaderboard.',
    execute(message, args, client) {
        const presenceData = client.presenceData || new Map();

        const leaderboard = Array.from(presenceData.entries())
            .flatMap(([userId, games]) =>
                Object.entries(games).map(([game, hours]) => ({
                    userId,
                    game,
                    hours,
                }))
            )
            .sort((a, b) => b.hours - a.hours)
            .slice(0, 10)
            .map((entry, index) =>
                `${index + 1}. <@${entry.userId}>: ${entry.hours} hours in ${entry.game}`
            );

        const embed = createEmbed(
            'Gaming Leaderboard',
            leaderboard.length ? leaderboard.join('\n') : 'N/A'
        );

        message.channel.send({ embeds: [embed] });
    },
};
