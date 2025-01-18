const { createEmbed } = require('../../utils/embedCreator');
const moment = require('moment');

module.exports = {
    name: 'userinfo',
    description: 'Display info about a user',
    async execute(message, args) {
        const member = message.mentions.members.first() || message.member;
        
        const embed = createEmbed({
            title: `User Information - ${member.user.tag}`,
            thumbnail: { url: member.user.displayAvatarURL({ dynamic: true }) },
            fields: [
                { name: 'Joined Server', value: moment(member.joinedAt).format('MMMM Do YYYY'), inline: true },
                { name: 'Account Created', value: moment(member.user.createdAt).format('MMMM Do YYYY'), inline: true },
                { name: 'Roles', value: member.roles.cache.map(r => r).join(', ') || 'None' }
            ]
        });

        message.channel.send({ embeds: [embed] });
    },
};
