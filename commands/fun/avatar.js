const embedUtils = require('../../utils/embedUtils');

module.exports = {
    name: 'avatar',
    description: 'Displays the profile picture of a user.',
    execute(message) {
        const user = message.mentions.users.first() || message.author;
        const embed = createEmbed(`${user.tag}'s Avatar`, 'Click the image to view it in full size.')
            .setImage(user.displayAvatarURL({ dynamic: true, size: 1024 }));

        message.channel.send({ embeds: [embed] });
    },
};
