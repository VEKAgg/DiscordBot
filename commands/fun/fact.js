const { createEmbed } = require('../../utils/embedUtils');

module.exports = {
    name: 'fact',
    description: 'Sends a random fact.',
    execute(message) {
        const facts = [
            'Honey never spoils.',
            'Bananas are berries, but strawberries are not.',
            'There are more stars in the universe than grains of sand on Earth.',
            'Octopuses have three hearts.',
            'A day on Venus is longer than a year on Venus.',
        ];

        const fact = facts[Math.floor(Math.random() * facts.length)];
        const embed = createEmbed('Random Fact', fact);
        message.channel.send({ embeds: [embed] });
    },
};
