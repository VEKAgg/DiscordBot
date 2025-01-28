const { createEmbed } = require('../../utils/embedCreator');

module.exports = {
    name: 'coinflip',
    description: 'Flip a coin',
    contributor: 'Sleepless',
    execute(message) {
        const result = Math.random() < 0.5;
        const outcomes = {
            true: { text: 'Heads', emoji: '🦅' },
            false: { text: 'Tails', emoji: '🦁' }
        };

        const embed = createEmbed({
            title: `${outcomes[result].emoji} Coin Flip`,
            description: `The coin landed on **${outcomes[result].text}**!`,
            color: '#FFD700',
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
