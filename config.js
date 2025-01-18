const { GatewayIntentBits } = require('discord.js');

module.exports = {
    intents: [
      GatewayIntentBits.Guilds,
      GatewayIntentBits.GuildMessages,
      GatewayIntentBits.MessageContent,
      GatewayIntentBits.GuildPresences,
    ],
    maxListeners: 15,
    richPresence: {
      activities: [
        {
          name: 'your server!',
          type: 'WATCHING', // Can also be PLAYING, LISTENING, STREAMING
        },
      ],
      status: 'online',
    },
    botDescription: 'A multi-purpose bot with utility, fun, and informational commands!',
    scheduledTaskCron: '0 * * * *', // Every hour as an example
    channels: {
        welcome: 'CHANNEL_ID',
        rules: 'CHANNEL_ID',
        roles: 'CHANNEL_ID',
        introductions: 'CHANNEL_ID',
        gaming: 'CHANNEL_ID',
        lfg: 'CHANNEL_ID',
        highlights: 'CHANNEL_ID'
    },
    roles: {
        member: 'ROLE_ID',
        verified: 'ROLE_ID',
        unverified: 'ROLE_ID',
        suspicious: 'ROLE_ID'
    },
    welcomeBanner: 'BANNER_URL',
};
  