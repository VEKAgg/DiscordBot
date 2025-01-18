const embedUtils = require('../../utils/embedUtils');

module.exports = {
    name: 'ban',
    description: 'Bans a user from the server.',
    execute(message, args) {
        if (!message.member.roles.cache.some((role) => role.name === 'Admin')) {
            return message.reply('You do not have permission to use this command!');
        }

        const target = message.mentions.users.first();
        if (!target) return message.reply('Please mention a user to ban.');

        const member = message.guild.members.resolve(target);
        member.ban()
            .then(() => message.reply(`${target.tag} has been banned.`))
            .catch((err) => {
                console.error(err);
                message.reply('An error occurred.');
            });
    },
};
