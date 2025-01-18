const embedUtils = require('../../utils/embedUtils');

module.exports = {
    name: 'emojiinfo',
    description: 'Show details about an emoji in the server.',
    execute(message, args, client) {
        const emoji = args[0];
        if (!emoji) return message.reply('Please provide an emoji to fetch details for.');

        const parsedEmoji = message.guild.emojis.cache.find((e) => e.name === emoji || e.id === emoji);
        if (!parsedEmoji) return message.reply('Emoji not found in this server.');

        const embed = createEmbed(
            'Emoji Info',
            `
            **Name:** ${parsedEmoji.name}
            **ID:** ${parsedEmoji.id}
            **Animated:** ${parsedEmoji.animated ? 'Yes' : 'No'}
            **Created At:** ${parsedEmoji.createdAt.toDateString()}
            [Emoji URL](${parsedEmoji.url})
            `,
        );
        message.channel.send({ embeds: [embed] });
    },
};
