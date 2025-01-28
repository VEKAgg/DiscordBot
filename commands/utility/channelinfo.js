const embedUtils = require('../../utils/embedUtils');

module.exports = {
    name: 'channelinfo',
    description: 'Get details about the current channel.',
    execute(message, args, client) {
        const channel = message.channel;
        const embed = createEmbed(
            'Channel Info',
            `
            **Name:** ${channel.name}
            **Type:** ${channel.type}
            **Topic:** ${channel.topic || 'No topic'}
            **Created At:** ${channel.createdAt.toDateString()}
            **NSFW:** ${channel.nsfw ? 'Yes' : 'No'}
            **Members:** ${channel.members.size}
            `,
            'ORANGE',
        );
        message.channel.send({ embeds: [embed] });
    },
};
