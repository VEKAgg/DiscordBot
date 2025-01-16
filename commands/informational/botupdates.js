const { createEmbed } = require('../../utils/embedUtils');

module.exports = {
    name: 'botupdates',
    description: 'Show the latest updates and the GitHub repository.',
    execute(message, args, client) {
        const embed = createEmbed(
            'Bot Updates',
            `
            **Latest Features:**
            - Added support for polls.
            - Enhanced stats with detailed data.
            - Utility commands like #time and #invite.

            **GitHub Repository:**
            [Click here to view the code](https://github.com/VEKAgg/DiscordBot)
            `,
            'GREEN',
        );
        message.channel.send({ embeds: [embed] });
    },
};
