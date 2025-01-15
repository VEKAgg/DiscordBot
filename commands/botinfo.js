const { createEmbed } = require('../utils/embedUtils');

module.exports = {
    name: 'botinfo',
    description: 'Displays information about the bot.',
    execute(message, args, client) {
        const embed = createEmbed('Bot Information', `
            **Name:** ${client.user.tag}
            **Version:** 0.1
            **Developed By:** VEKA Team
            **Repository:** [GitHub](https://github.com/VEKAgg/DiscordBot)
        `);
        message.channel.send({ embeds: [embed] });
    },
};
