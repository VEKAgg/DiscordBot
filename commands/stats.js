const { createEmbed } = require('../utils/embedUtils');
const os = require('os');

module.exports = {
    name: 'stats',
    description: 'Displays bot statistics.',
    execute(message, args, client) {
        const uptime = process.uptime();
        const memoryUsage = process.memoryUsage().heapUsed / 1024 / 1024;
        const cpu = os.cpus()[0].model;

        const embed = createEmbed('Bot Statistics', `
            **Uptime:** ${Math.floor(uptime / 60)} minutes
            **Memory Usage:** ${memoryUsage.toFixed(2)} MB
            **CPU:** ${cpu}
            **Servers:** ${client.guilds.cache.size}
        `);
        message.channel.send({ embeds: [embed] });
    },
};
