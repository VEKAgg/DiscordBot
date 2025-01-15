const { createEmbed } = require('../utils/embedUtils');

module.exports = {
    name: 'userinfo',
    description: 'Displays information about a user.',
    execute(message) {
        const { author } = message;

        const embed = createEmbed('User Information', `
            **Username:** ${author.tag}
            **ID:** ${author.id}
            **Created At:** ${author.createdAt.toDateString()}
        `);
        message.channel.send({ embeds: [embed] });
    },
};
