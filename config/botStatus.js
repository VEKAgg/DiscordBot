const { ActivityType } = require('discord.js');

module.exports = {
    interval: 15000, // Change status every 15 seconds
    statuses: [
        {
            type: ActivityType.Watching,
            text: '{memberCount} members'
        },
        {
            type: ActivityType.Listening,
            text: '{serverCount} servers'
        },
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