const { createEmbed } = require('../../utils/embedUtils');

module.exports = {
    name: 'coinflip',
    description: 'Flips a coin and returns Heads or Tails.',
    execute(message) {
        const result = Math.random() < 0.5 ? 'Heads' : 'Tails';
        const embed = createEmbed('Coin Flip', `The coin landed on **${result}**.`);
        message.channel.send({ embeds: [embed] });
    },
};
