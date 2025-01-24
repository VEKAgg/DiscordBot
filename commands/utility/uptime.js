const { EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'uptime',
    description: 'Shows bot uptime',
    async execute(message) {
        const uptime = process.uptime();
        const days = Math.floor(uptime / 86400);
        const hours = Math.floor(uptime / 3600) % 24;
        const minutes = Math.floor(uptime / 60) % 60;
        const seconds = Math.floor(uptime % 60);

        const embed = new EmbedBuilder()
            .setTitle('🕒 Bot Uptime')
            .setDescription(`I've been online for:\n${days}d ${hours}h ${minutes}m ${seconds}s`)
            .setColor('#00ff00')
            .setTimestamp();

        message.channel.send({ embeds: [embed] });
    }
};
