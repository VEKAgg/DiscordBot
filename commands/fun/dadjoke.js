const { createEmbed } = require('../../utils/embedUtils');
const fetch = require('node-fetch');

module.exports = {
    name: 'dadjoke',
    description: 'Send a random dad joke.',
    async execute(message, args, client) {
        const response = await fetch('https://icanhazdadjoke.com/', {
            headers: { Accept: 'application/json' },
        });
        const data = await response.json();
        message.channel.send({ embeds: [createEmbed('Dad Joke', data.joke)] });
    },
};
