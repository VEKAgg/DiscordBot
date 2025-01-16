const { EmbedBuilder } = require('discord.js');

module.exports = {
  name: 'stock',
  description: 'Show stock market prices for a company.',
  execute(message, args) {
    if (!args[0]) {
      return message.channel.send('Please provide a stock symbol. Example: `#stock TSLA`');
    }
    const symbol = args[0].toUpperCase();
    // Placeholder stock price
    const price = `The stock price of ${symbol} is $1,000.`;
    const embed = new EmbedBuilder()
      .setTitle(`Stock Price: ${symbol}`)
      .setDescription(price)
      .setColor('GREEN');
    message.channel.send({ embeds: [embed] });
  },
};
