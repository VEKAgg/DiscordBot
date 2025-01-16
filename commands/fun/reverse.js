const { createEmbed } = require('../../utils/embedUtils');

module.exports = {
    name: 'reverse',
    description: 'Reverse a given text.',
    execute(message, args, client) {
        const input = args.join(' ');
        if (!input) return message.reply('Please provide text to reverse.');

        const reversedText = input.split('').reverse().join('');
        message.channel.send({ embeds: [createEmbed('Reversed Text', reversedText, 'ORANGE')] });
    },
};
