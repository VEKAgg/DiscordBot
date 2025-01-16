const { EmbedBuilder } = require('discord.js');

module.exports = {
  name: 'crypto',
  description: 'Display cryptocurrency prices (e.g., Bitcoin).',
  execute(message, args) {
    if (!args[0]) {
      return message.channel.send('Please provide a cryptocurrency symbol. Example: `#crypto BTC`');
    }
    const symbol = args[0].toUpperCase();
    // Placeholder crypto price
    const price = `Price of ${symbol} is $40,000`;
    const embed = new EmbedBuilder()
      .setTitle(`Crypto Price: ${symbol}`)
      .setDescription(price)
      .setColor('GOLD');
    message.channel.send({ embeds: [embed] });
  },
};
