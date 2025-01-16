const { createEmbed } = require('../../utils/embedUtils');
const fetch = require('node-fetch');

module.exports = {
    name: 'meme',
    description: 'Fetch a random meme from Reddit.',
    async execute(message, args, client) {
        const response = await fetch('https://www.reddit.com/r/memes/random.json');
        const data = await response.json();
        const meme = data[0].data.children[0].data;

        message.channel.send({
            embeds: [
                createEmbed(meme.title, '', 'ORANGE').setImage(meme.url).setFooter({ text: `👍 ${meme.ups}` }),
            ],
        });
    },
};
