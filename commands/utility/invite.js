const embedUtils = require('../../utils/embedUtils');

module.exports = {
    name: 'invite',
    description: 'Generate an invite link for the bot.',
    execute(message, args, client) {
        const inviteLink = `https://discord.com/oauth2/authorize?client_id=${client.user.id}&permissions=8&scope=bot%20applications.commands`;
        const embed = createEmbed('Invite the Bot!', `[Click here to invite me!](${inviteLink})`, 'ORANGE');
        message.channel.send({ embeds: [embed] });
    },
};
