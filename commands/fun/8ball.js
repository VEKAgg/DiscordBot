const { EmbedBuilder } = require('discord.js');

module.exports = {
    name: '8ball',
    description: 'Ask the magic 8-ball a question',
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
                'As I see it, yes! 👍',
                'Most likely! 🎲',
                'Outlook good! 🌅',
                'Yes! ✅',
                'Signs point to yes! 🎭'
            ],
            neutral: [
                'Reply hazy, try again... 🌫️',
                'Ask again later... ⏳',
                'Better not tell you now... 🤐',
                'Cannot predict now... 🔮',
                'Concentrate and ask again... 🧘‍♂️'
            ],
            negative: [
                'Don\'t count on it! ❌',
                'My reply is no! 🚫',
                'My sources say no! 📚',
                'Outlook not so good... 😬',
                'Very doubtful! 😔'
            ]
        };

        const category = ['positive', 'neutral', 'negative'][Math.floor(Math.random() * 3)];
        const answer = responses[category][Math.floor(Math.random() * responses[category].length)];

        const colors = {
            positive: '#00FF00',
            neutral: '#FFD700',
            negative: '#FF0000'
        };

        const embed = new EmbedBuilder()
            .setTitle('🎱 Magic 8-Ball')
            .addFields([
                { name: '❓ Question', value: question, inline: false },
                { name: '📝 Answer', value: answer, inline: false },
                { name: '💭 Note', value: 'Remember, the 8-ball is just for fun!', inline: false }
            ])
            .setColor(colors[category])
            .setFooter({ text: `Asked by ${message.author.tag}` })
            .setTimestamp();

        message.channel.send({ embeds: [embed] });
    },
};
