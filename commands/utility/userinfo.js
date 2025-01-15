const { createEmbed } = require('../../utils/embedUtils');

module.exports = {
    name: 'userinfo',
    description: 'Displays detailed information about a user.',
    execute(message) {
        const member = message.mentions.members.first() || message.member;
        const { user } = member;

        const embed = createEmbed('User Information', `
            **Username:** ${user.tag}
            **User ID:** ${user.id}
            **Account Created:** ${user.createdAt.toDateString()}
            **Joined Server:** ${member.joinedAt?.toDateString() || 'N/A'}
            **Roles:** ${member.roles.cache.map((role) => role.name).join(', ')}
        `);

        if (user.displayAvatarURL()) {
            embed.setThumbnail(user.displayAvatarURL({ dynamic: true, size: 1024 }));
        }

        message.channel.send({ embeds: [embed] });
    },
};
