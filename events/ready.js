module.exports = {
    name: 'ready',
    once: true,
    execute(client) {
        console.log(`Logged in as ${client.user.tag}!`);

        setInterval(() => {
            const serverCount = client.guilds.cache.size;
            const memberCount = client.guilds.cache.reduce((acc, guild) => acc + guild.memberCount, 0);

            const statuses = [
                `Serving ${serverCount} servers`,
                `Serving ${memberCount} members`,
                `Type #help for commands`,
            ];

            const status = statuses[Math.floor(Math.random() * statuses.length)];

            client.user.setPresence({
                activities: [{ name: status, type: 'PLAYING' }],
                status: 'online',
            });
        }, 10000); // Update every 10 seconds
    },
};
