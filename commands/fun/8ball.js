const { createEmbed } = require('../../utils/embedCreator');

module.exports = {
    name: '8ball',
    description: 'Ask the magic 8-ball a question',
    contributor: 'Sleepless',
    execute(message, args) {
        const question = args.join(' ');
        if (!question) {
            return message.reply('Please ask a yes/no question. Example: `#8ball will I win the lottery?`');
        }

        const responses = {
            positive: [
                'It is certain! ✨',
                'Without a doubt! 💫',
                'You may rely on it! 🌟',
                'Yes - definitely! 🎯',
                'As I see it, yes! 👍'
            ],
            neutral: [
                'Reply hazy, try again 🌫️',
                'Ask again later ⏳',
                'Better not tell you now 🤐',
                'Cannot predict now 🔮',
                'Concentrate and ask again 🧘'
            ],
            negative: [
                'Don\'t count on it! ❌',
                'My reply is no! 🚫',
                'My sources say no! 📚',
                'Outlook not so good! 🌧️',
                'Very doubtful! ⚠️'
            ]
        };

        const colors = {
            positive: '#2ECC71',
            neutral: '#F1C40F',
            negative: '#E74C3C'
        };

        const category = Object.keys(responses)[Math.floor(Math.random() * 3)];
        const answer = responses[category][Math.floor(Math.random() * responses[category].length)];

        const embed = createEmbed({
            title: '🎱 Magic 8-Ball',
            color: colors[category],
            fields: [
                { name: '❓ Question', value: question, inline: false },
                { name: '📝 Answer', value: answer, inline: false },
                { name: '💭 Note', value: 'Remember, the 8-ball is just for fun!', inline: false }
            ],
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
    }
};
