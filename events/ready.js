module.exports = {
    name: 'ready',
    once: true,
    execute(client) {
        console.log(`Logged in as ${client.user.tag}!`);

        // Rotating statuses
        const statuses = [
            'Under Development | veka.gg',
            'VEKA Bot v0.1 | Contribute on GitHub!',
            'Type #help for commands!',
        ];

        let index = 0;
        setInterval(() => {
            client.user.setPresence({
                activities: [{ name: statuses[index], type: 'WATCHING' }],
                status: 'online',
            });
            index = (index + 1) % statuses.length; // Loop through statuses
        }, 10000); // Change every 10 seconds
    },
};
