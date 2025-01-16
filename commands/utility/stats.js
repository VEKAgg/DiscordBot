const { createEmbed } = require('../../utils/embedUtils');

module.exports = {
    name: 'stats',
    description: 'Displays bot and server statistics.',
    execute(message, args, client) {
        const totalMessages = client.totalMessages || 0;
        const serverMessages = client.serverMessages || 0;
        const totalUsers = client.users.cache.size;
        const totalGuilds = client.guilds.cache.size;
        const voiceChannelUsers = client.voice.adapters.size;

        const embed = createEmbed(
            'Bot & Server Stats',
            `
            **Total Messages Bot Read:** ${totalMessages}
            **Total Messages in Server:** ${serverMessages}
            **Total Users Interacted With:** ${totalUsers}
            **Total Servers Bot is In:** ${totalGuilds}
            **Users in Voice Channels (All Servers):** ${voiceChannelUsers}
            `,
        );

        message.channel.send({ embeds: [embed] });
    },
};
