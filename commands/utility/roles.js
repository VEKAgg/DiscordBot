const embedUtils = require('../../utils/embedUtils');

module.exports = {
    name: 'roles',
    description: 'List all roles in the server.',
    execute(message, args, client) {
        const roles = message.guild.roles.cache
            .filter((role) => role.name !== '@everyone')
            .map((role) => `${role.name} - ${role.members.size} members`);

        const embed = createEmbed('Server Roles', roles.join('\n') || 'No roles found.');
        message.channel.send({ embeds: [embed] });
    },
};
