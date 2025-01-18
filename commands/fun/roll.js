const { EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'roll',
    description: 'Roll one or more dice with custom sides',
    execute(message, args) {
        const diceRegex = /^(\d+)?d(\d+)$/i;  // Format: XdY where X = number of dice, Y = sides
        const input = args[0] || 'd6';  // Default to 1d6
        const match = input.match(diceRegex);

        if (!match) {
            return message.reply('Invalid format! Use `#roll [X]d[Y]` (e.g., `#roll 2d6` or `#roll d20`)');
        }

        const numDice = parseInt(match[1]) || 1;
        const sides = parseInt(match[2]);

        if (numDice > 100) {
            return message.reply('Maximum 100 dice allowed!');
        }
        if (sides <= 1 || sides > 1000) {
            return message.reply('Number of sides must be between 2 and 1000!');
        }

        const rolls = [];
        let total = 0;
        for (let i = 0; i < numDice; i++) {
            const roll = Math.floor(Math.random() * sides) + 1;
            rolls.push(roll);
            total += roll;
        }

        const diceEmoji = {
            4: '🎲',
            6: '🎲',
            8: '🎯',
            10: '🎯',
            12: '🎯',
            20: '🎲',
            100: '💯'
        }[sides] || '🎲';

        const embed = new EmbedBuilder()
            .setTitle(`${diceEmoji} Dice Roll`)
            .setDescription(`Rolling ${numDice}d${sides}...`)
            .addFields([
                { name: 'Individual Rolls', value: rolls.join(', '), inline: false },
                { name: 'Total', value: total.toString(), inline: true },
                { name: 'Average', value: (total / numDice).toFixed(2), inline: true }
            ])
            .setColor('#4169E1')
            .setFooter({ text: `Requested by ${message.author.tag}` })
            .setTimestamp();

        if (numDice === 1 && (rolls[0] === 1 || rolls[0] === sides)) {
            embed.addFields({
                name: 'Special Result',
                value: rolls[0] === 1 ? 'Critical Fail! 😱' : 'Critical Success! 🎉',
                inline: false
            });
        }

        message.channel.send({ embeds: [embed] });
    },
};
