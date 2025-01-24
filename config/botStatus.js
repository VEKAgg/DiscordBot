const { ActivityType } = require('discord.js');

module.exports = {
    interval: 15000, // 15 seconds
    statuses: [
        {
            type: ActivityType.Playing,
            text: 'with {memberCount} members'
        },
        {
            type: ActivityType.Watching,
            text: 'over {serverCount} servers'
        },
        {
            type: ActivityType.Listening,
            text: 'to /help commands'
        },
        {
            type: ActivityType.Competing,
            text: 'in {activeVoice} voice chats'
        },
        {
            type: ActivityType.Custom,
            text: '🎮 Gaming with friends'
        },
        {
            type: ActivityType.Playing,
            text: 'Type /help for commands'
        },
        {
            type: ActivityType.Watching,
            text: '{messageCount} messages today'
        }
    ]
}; 