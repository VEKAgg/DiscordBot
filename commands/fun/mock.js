const { createEmbed } = require('../../utils/embedUtils');

module.exports = {
    name: 'mock',
    description: 'Mock text by alternating capitalization.',
    execute(message, args, client) {
        const input = args.join(' ');
        if (!input) return message.reply('Please provide text to mock.');

        const mockedText = input
            .split('')
            .map((char, index) => (index % 2 === 0 ? char.toLowerCase() : char.toUpperCase()))
            .join('');

        message.channel.send({ embeds: [createEmbed('Mocked Text', mockedText, 'ORANGE')] });
    },
};
