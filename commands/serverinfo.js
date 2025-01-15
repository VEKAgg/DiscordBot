const { createEmbed } = require('../utils/embedUtils');

module.exports = {
    name: 'serverinfo',
    description: 'Displays information about the server.',
    execute(message) {
        const { guild } = message;

        const embed = createEmbed('Server Information', `
            **Server Name:** ${guild.name}
            **Members:** ${guild.memberCount}
            **Region:** ${guild.preferredLocale}
            **Owner:** <@${guild.ownerId}>
        `);
        message.channel.send({ embeds: [embed] });
    },
};
