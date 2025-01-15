const { createEmbed } = require('../utils/embedUtils');

module.exports = {
    name: 'help',
    description: 'Provides usage instructions for the bot.',
    execute(message, args, client) {
        const commands = client.commands;
        const categories = {
            Utility: ['userinfo', 'serverinfo', 'botinfo', 'pfp'],
            Fun: ['ping', 'remindme', 'gaming-leaderboard'],
            Admin: ['logging', 'schedule'],
        };

        let description = 'Here are the available commands:\n\n';
        for (const [category, cmds] of Object.entries(categories)) {
            description += `**${category}**:\n${cmds
                .map((cmd) => `#${cmd}: ${commands.get(cmd)?.description || ''}`)
                .join('\n')}\n\n`;
        }

        const embed = createEmbed('Help - Usage Instructions', description);
        message.channel.send({ embeds: [embed] });
    },
};
