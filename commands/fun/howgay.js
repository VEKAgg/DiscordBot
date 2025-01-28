const { createEmbed } = require('../../utils/embedCreator');

module.exports = {
    name: 'howgay',
    description: 'Check how gay someone is (just for fun!)',
    contributor: 'Sleepless',
    execute(message, args) {
        const target = message.mentions.users.first() || 
            (args.length ? args.join(' ') : message.author.username);
        const percentage = Math.floor(Math.random() * 101);
        
        const getColor = (percent) => {
            if (percent < 30) return '#00FF00';
            if (percent < 70) return '#FFA500';
            return '#FF69B4';
        };

        const getMessage = (percent) => {
            if (percent < 30) return 'Pretty straight! 😎';
            if (percent < 70) return 'A bit curious? 🤔';
            return 'Super gay! 🌈';
        };

        const embed = createEmbed({
            title: '🏳️‍🌈 Gay Rate Machine',
            description: `${typeof target === 'string' ? target : target.username} is ${percentage}% gay!\n\n${getMessage(percentage)}`,
            color: getColor(percentage),
            fields: [
                {
                    name: 'Gay Level',
                    value: `${'🟦'.repeat(Math.floor(percentage/10))}${'⬜'.repeat(10-Math.floor(percentage/10))}`,
                    inline: false
                }
            ],
            author: {
                name: message.author.tag,
                iconURL: message.author.displayAvatarURL({ dynamic: true })
            },
            footer: {
                text: `Contributor: ${module.exports.contributor} • VEKA | Just for fun, don't take it seriously!`,
                iconURL: message.client.user.displayAvatarURL()
            }
        });

        message.channel.send({ embeds: [embed] });
    }
};
  