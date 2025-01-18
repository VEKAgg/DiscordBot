const embedUtils = require('../../utils/embedUtils');

module.exports = {
    name: 'serverinfo',
    description: 'Displays detailed information about the server.',
    execute(message) {
        const { guild } = message;

        const embed = createEmbed('Server Information', `
            **Server Name:** ${guild.name}
            **Server ID:** ${guild.id}
            **Owner:** <@${guild.ownerId}>
            **Created On:** ${guild.createdAt.toDateString()}
            **Total Members:** ${guild.memberCount}
            **Boost Level:** ${guild.premiumTier}
            **Boost Count:** ${guild.premiumSubscriptionCount || 0}
        `);

        if (guild.iconURL()) {
            embed.setThumbnail(guild.iconURL({ dynamic: true, size: 1024 }));
        }

        message.channel.send({ embeds: [embed] });
    },
};
