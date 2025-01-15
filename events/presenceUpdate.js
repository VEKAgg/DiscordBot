module.exports = {
    name: 'presenceUpdate',
    execute(oldPresence, newPresence, client) {
        if (!newPresence.activities) return;

        const userId = newPresence.userId;
        const activity = newPresence.activities.find((act) => act.type === 'PLAYING');
        if (activity) {
            const gameName = activity.name;
            const duration = presenceData.get(userId)?.[gameName] || 0;

            presenceData.set(userId, {
                ...presenceData.get(userId),
                [gameName]: duration + 1,
            });
        }
    },
};
