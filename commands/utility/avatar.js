const { createEmbed } = require('../../utils/embedCreator');

module.exports = {
    name: 'avatar',
    description: 'Get user avatar',
    contributor: 'Sleepless',
    async execute(message, args) {
        const user = message.mentions.users.first() || message.author;
        
        const embed = createEmbed({
            title: `${user.username}'s Avatar`,
            description: `[Click to download](${user.displayAvatarURL({ size: 4096, dynamic: true })})`,
            image: { url: user.displayAvatarURL({ size: 4096, dynamic: true }) },
            author: {
                name: message.author.tag,
                iconURL: message.author.displayAvatarURL({ dynamic: true })
            },
            footer: {
                text: `Contributor: ${module.exports.contributor} • VEKA`,
                iconURL: message.client.user.displayAvatarURL()
            }
        });

        message.channel.send({ embeds: [embed] });
    },
};