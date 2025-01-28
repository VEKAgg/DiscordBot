const { EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'lmgtfy',
    description: 'Generate a "Let Me Google That For You" link',
    async execute(message, args) {
        if (!args.length) {
            return message.reply('Please provide a search query. Example: `#lmgtfy how to code`');
        }

        const query = encodeURIComponent(args.join(' '));
        const url = `https://lmgtfy.app/?q=${query}`;

        const embed = new EmbedBuilder()
            .setTitle('🔍 Let me Google that for you')
            .setDescription(`[Click here to see how to search for: ${args.join(' ')}](${url})`)
            .setColor('#4285F4')
            .setFooter({ text: 'Tip: Share this link with someone who needs help with basic Google searches!' })
            .setTimestamp();

        message.channel.send({ embeds: [embed] });
    },
};
  