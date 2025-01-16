const { createEmbed } = require('../../utils/embedUtils');

module.exports = {
    name: 'poll',
    description: 'Create a poll with multiple options.',
    execute(message, args, client) {
        const [question, ...options] = args.join(' ').split('|');
        if (!question || options.length < 2) {
            return message.reply(
                'Please provide a question and at least two options separated by `|`. Example: `#poll "What is your favorite color?" | Red | Blue | Green`',
            );
        }

        const pollEmbed = createEmbed(
            `📊 Poll: ${question}`,
            options.map((option, index) => `${index + 1}. ${option}`).join('\n'),
        );

        message.channel
            .send({ embeds: [pollEmbed] })
            .then(async (pollMessage) => {
                const emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣'];
                for (let i = 0; i < options.length && i < emojis.length; i++) {
                    await pollMessage.react(emojis[i]);
                }
            })
            .catch((err) => console.error('Error sending poll:', err));
    },
};
