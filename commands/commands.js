const { createEmbed } = require('../utils/embedUtils');

module.exports = {
    name: 'commands',
    description: 'Lists all available commands grouped by category.',
    execute(message, args, client) {
        const commands = client.commands.map((cmd) => `#${cmd.name}`).join(', ');
        const embed = createEmbed('Available Commands', commands || 'No commands available.');
        message.channel.send({ embeds: [embed] });
    },
};
