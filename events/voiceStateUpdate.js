module.exports = {
    name: 'voiceStateUpdate',
    execute(oldState, newState, client) {
        if (!newState.channel || newState.member.user.bot) return;

        const userId = newState.member.user.id;
        const startTime = newState.joinedAt || Date.now();

        newState.channel.client.voiceTimers = newState.channel.client.voiceTimers || {};
        newState.channel.client.voiceTimers[userId] = startTime;

        // Award points on leave
        if (!newState.channelId && oldState.channelId) {
            const timeSpent = Date.now() - client.voiceTimers[userId];
            const pointsEarned = Math.floor(timeSpent / 60000); // 1 point per minute
            const totalPoints = (client.points.get(userId) || 0) + pointsEarned;

            client.points.set(userId, totalPoints);

            delete client.voiceTimers[userId];
        }
    },
};
