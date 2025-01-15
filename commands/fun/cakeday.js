const { createEmbed } = require('../../utils/embedUtils');

module.exports = {
    name: 'cakeday',
    description: 'Congratulates a user on their account anniversary.',
    execute(message) {
        const user = message.mentions.users.first() || message.author;
        const createdAt = user.createdAt;

        const embed = createEmbed('🎉 Happy Cake Day!', `
            Congrats, ${user.tag}!
            Your account was created on ${createdAt.toDateString()}.
        `);

        message.channel.send({ embeds: [embed] });
    },
};
