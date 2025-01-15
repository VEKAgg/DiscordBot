const { createEmbed } = require('../../utils/embedUtils');

module.exports = {
    name: 'roll',
    description: 'Rolls a die up to the specified number.',
    execute(message, args) {
        const max = parseInt(args[0], 10) || 6; // Default to 6 if no number is provided
        if (isNaN(max) || max <= 0) {
            const embed = createEmbed('Error', 'Please provide a valid number greater than 0.', 0xFF0000);
            return message.channel.send({ embeds: [embed] });
        }

        const result = Math.floor(Math.random() * max) + 1;
        const embed = createEmbed('Dice Roll', `You rolled a **${result}** (1-${max}).`);
        message.channel.send({ embeds: [embed] });
    },
};
