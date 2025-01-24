const { PermissionFlagsBits } = require('discord.js');

module.exports = {
    name: 'channel',
    description: 'Manage bot channels',
    permissions: [PermissionFlagsBits.ManageChannels],
    async execute(message, args) {
        const [action, type] = args;
        
        if (action === 'create') {
            const channelTypes = {
                'dashboard': { name: 'bot-dashboard', topic: 'Server statistics and leaderboards' },
                'logs': { name: 'server-logs', topic: 'Server activity logging' },
                'staff': { name: 'staff-channel', topic: 'Staff notifications and controls' }
            };

            const channelConfig = channelTypes[type];
            if (!channelConfig) {
                return message.reply('Valid channel types: dashboard, logs, staff');
            }

            const channel = await message.guild.channels.create({
                name: channelConfig.name,
                topic: channelConfig.topic
            });

            message.reply(`Created channel ${channel}`);
        }
    }
}; 