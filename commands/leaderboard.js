const messageCounts = new Map(); // In-memory storage for message counts

module.exports = {
    name: 'leaderboard',
    description: 'Shows the message leaderboard',
    execute(message) {
        const sorted = Array.from(messageCounts.entries())
            .sort((a, b) => b[1] - a[1])
            .slice(0, 5)
            .map(([userId, count], index) => `${index + 1}. <@${userId}>: ${count} messages`)
            .join('\n');

        message.channel.send({
            content: '**Message Leaderboard:**\n' + (sorted || 'No messages yet!'),
        });
    },
};
