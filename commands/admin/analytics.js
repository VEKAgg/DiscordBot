const { EmbedBuilder, PermissionFlagsBits } = require('discord.js');
const Analytics = require('../../utils/analytics');

module.exports = {
    name: 'analytics',
    description: 'View server analytics',
    permissions: [PermissionFlagsBits.Administrator],
    async execute(message, args) {
        try {
            const type = args[0] || 'overview';
            const timeframe = args[1] || '7d';
            
            const stats = await Analytics.getStats(message.guild.id, type, timeframe);
            
            if (!stats || Object.keys(stats).length === 0) {
                return message.reply('No analytics data available for the specified timeframe.');
            }

            const embed = new EmbedBuilder()
                .setTitle(`📊 Server Analytics - ${type}`)
                .setDescription('Server activity statistics')
                .addFields(
                    Object.entries(stats).map(([key, value]) => ({
                        name: key.charAt(0).toUpperCase() + key.slice(1).replace(/([A-Z])/g, ' $1'),
                        value: typeof value === 'number' ? value.toLocaleString() : String(value),
                        inline: true
                    }))
                )
                .setColor('#00ff00')
                .setFooter({ text: `Timeframe: ${timeframe}` })
                .setTimestamp();
                
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            console.error('Analytics Error:', error);
            message.reply('Failed to fetch analytics data.');
        }
    }
}; 