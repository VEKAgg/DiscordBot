const presenceData = new Map();

module.exports = {
    name: 'gaming-leaderboard',
    description: 'Shows the gaming leaderboard',
    execute(message) {
        const leaderboard = Array.from(presenceData.entries())
            .flatMap(([userId, games]) =>
                Object.entries(games).map(([game, hours]) => ({
                    userId,
                    game,
                    hours,
                }))
            )
            .sort((a, b) => b.hours - a.hours)
            .slice(0, 5)
            .map((entry, index) => `${index + 1}. <@${entry.userId}>: ${entry.hours} hours in ${entry.game}`)
            .join('\n');

        message.channel.send({
            content: '**Gaming Leaderboard:**\n' + (leaderboard || 'No data yet!'),
        });
    },
};
