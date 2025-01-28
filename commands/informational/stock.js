const { EmbedBuilder } = require('discord.js');
const axios = require('axios');
const NodeCache = require('node-cache');
const cache = new NodeCache({ stdTTL: 300 }); // Cache for 5 minutes

module.exports = {
  name: 'stock',
  description: 'Get real-time stock information',
  async execute(message, args) {
    if (!args[0]) return message.reply('Please provide a stock symbol (e.g., AAPL)');
    
    const symbol = args[0].toUpperCase();
    const cachedData = cache.get(symbol);

    if (cachedData) {
      message.channel.send({ embeds: [cachedData] });
      return;
    }

    const API_KEY = process.env.ALPHAVANTAGE_API_KEY;
    const url = `https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=${symbol}&apikey=${API_KEY}`;

    try {
      const response = await axios.get(url);
      const quote = response.data['Global Quote'];

      if (!quote || !quote['05. price']) {
        return message.reply('Could not find that stock symbol!');
      }

      const embed = new EmbedBuilder()
        .setTitle(`${symbol} Stock Information`)
        .addFields([
          { name: 'Price', value: `$${parseFloat(quote['05. price']).toFixed(2)}`, inline: true },
          { name: 'Change', value: quote['09. change'], inline: true },
          { name: 'Change %', value: quote['10. change percent'], inline: true },
          { name: 'Volume', value: quote['06. volume'], inline: true }
        ])
        .setColor(parseFloat(quote['09. change']) >= 0 ? '#00ff00' : '#ff0000')
        .setTimestamp();

      cache.set(symbol, embed);
      message.channel.send({ embeds: [embed] });
    } catch (error) {
      message.reply('Error fetching stock information!');
    }
  },
};
