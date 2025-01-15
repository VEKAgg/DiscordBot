const { createEmbed } = require('../utils/embedUtils');

module.exports = {
    name: 'help',
    description: 'Lists all available commands.',
    execute(message, args, client) {
        const commands = client.commands.map(cmd => `**#${cmd.name}**: ${cmd.description}`).join('\n');
        const embed = createEmbed('Help', `Here are the available commands:\n\n${commands}`);
        message.channel.send({ embeds: [embed] });
    },
};
