const { EmbedBuilder, version: discordVersion } = require('discord.js');
const { version } = require('../../package.json');
const os = require('os');

module.exports = {
    name: 'botinfo',
    description: 'Shows bot information',
    async execute(message) {
        const embed = new EmbedBuilder()
            .setTitle('🤖 Bot Information')
            .addFields([
                { name: 'Bot Version', value: version, inline: true },
                { name: 'Discord.js', value: discordVersion, inline: true },
                { name: 'Node.js', value: process.version, inline: true },
                { name: 'Memory Usage', value: `${(process.memoryUsage().heapUsed / 1024 / 1024).toFixed(2)} MB`, inline: true },
                { name: 'Uptime', value: this.formatUptime(process.uptime()), inline: true },
                { name: 'Servers', value: message.client.guilds.cache.size.toString(), inline: true }
            ])
            .setColor('#00ff00')
            .setTimestamp();

        message.channel.send({ embeds: [embed] });
    },

    formatUptime(uptime) {
        const days = Math.floor(uptime / 86400);
        const hours = Math.floor(uptime / 3600) % 24;
        const minutes = Math.floor(uptime / 60) % 60;
        return `${days}d ${hours}h ${minutes}m`;
    },

    async setupDashboard(message) {
        const channel = message.mentions.channels.first() || message.channel;
        await DashboardConfig.findOneAndUpdate(
            { guildId: message.guild.id },
            { channelId: channel.id },
            { upsert: true }
        );
        message.reply(`Dashboard will be displayed in ${channel}`);
    },

    async setupAnalytics(message) {
        const config = await AnalyticsConfig.findOneAndUpdate(
            { guildId: message.guild.id },
            { enabled: true },
            { upsert: true, new: true }
        );
        message.reply('Analytics system has been enabled for this server.');
    }
};
