const { createEmbed } = require('../../utils/embedCreator');

module.exports = {
    name: 'roll',
    description: 'Roll dice with custom sides and amount',
    contributor: 'Sleepless',
    execute(message, args) {
        const usage = 'Usage: #roll <number of dice>d<number of sides> (e.g., #roll 2d6)';
        
        if (!args.length) {
            return message.reply(usage);
        }

        const diceRegex = /^(\d+)?d(\d+)$/i;
        const match = args[0].match(diceRegex);

        if (!match) {
            return message.reply(usage);
        }

        const numDice = Math.min(parseInt(match[1] || '1'), 100);
        const numSides = Math.min(parseInt(match[2]), 1000);

        if (numDice < 1 || numSides < 2) {
            return message.reply('Invalid dice configuration! Number of dice must be at least 1, and sides must be at least 2.');
        }

        const rolls = [];
        let total = 0;

        for (let i = 0; i < numDice; i++) {
            const roll = Math.floor(Math.random() * numSides) + 1;
            rolls.push(roll);
            total += roll;
        }

        const embed = createEmbed({
            title: '🎲 Dice Roll Results',
            description: `Rolling ${numDice}d${numSides}...`,
            color: '#4169E1',
            fields: [
                { name: 'Individual Rolls', value: rolls.join(', '), inline: false },
                { name: 'Total', value: total.toString(), inline: true },
                { name: 'Average', value: (total / numDice).toFixed(2), inline: true }
            ],
            author: {
                name: message.author.tag,
                iconURL: message.author.displayAvatarURL({ dynamic: true })
            },
            footer: {
                text: `Contributor: ${module.exports.contributor} • VEKA`,
                iconURL: message.client.user.displayAvatarURL()
            }
        });

        message.channel.send({ embeds: [embed] });
    }
};