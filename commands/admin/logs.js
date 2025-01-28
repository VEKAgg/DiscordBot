const { EmbedBuilder, PermissionFlagsBits } = require('discord.js');

module.exports = {
    name: 'logs',
    description: 'View server logs',
    permissions: [PermissionFlagsBits.ViewAuditLog],
    async execute(message, args) {
        const type = args[0]?.toUpperCase() || 'ALL';
        const logs = await message.client.logger.getLogs(message.guild, type);

        const embed = new EmbedBuilder()
            .setTitle(`📋 Server Logs - ${type}`)
            .setDescription(
                logs.map(log => 
                    `[${new Date(log.timestamp).toLocaleString()}] ${log.content}`
                ).join('\n')
            )
            .setColor('#0099ff')
            .setTimestamp();

        message.channel.send({ embeds: [embed] });
    }
}; 