const { createEmbed } = require('../../utils/embedUtils');

module.exports = {
    name: '8ball',
    description: 'Answers a yes/no question with a random response.',
    execute(message, args) {
        const question = args.join(' ');
        if (!question) {
            const embed = createEmbed('Error', 'Please ask a yes/no question.', 0xFF0000);
            return message.channel.send({ embeds: [embed] });
        }

        const responses = [
            'Yes.', 'No.', 'Maybe.', 'Definitely.', 'I don’t think so.',
            'Ask again later.', 'Absolutely!', 'Not a chance.',
        ];
        const answer = responses[Math.floor(Math.random() * responses.length)];
        const embed = createEmbed('🎱 8-Ball', `Question: ${question}\nAnswer: **${answer}**`);
        message.channel.send({ embeds: [embed] });
    },
};
