const { EmbedBuilder } = require('discord.js');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const NodeCache = require('node-cache');
const cache = new NodeCache({ stdTTL: 300 }); // Cache for 5 minutes

module.exports = {
  name: 'crypto',
  description: 'Get cryptocurrency price information',
  async execute(message, args) {
    if (!args[0]) return message.reply('Please provide a cryptocurrency symbol (e.g., BTC)');
    
    const symbol = args[0].toUpperCase();
    const cachedData = cache.get(symbol);

    if (cachedData) {
      message.channel.send({ embeds: [cachedData] });
      return;
    }

    const rateCheck = await rateLimiter.checkLimit('crypto');
    if (!rateCheck.success) {
      return message.reply(rateCheck.message);
    }

    try {
      const response = await fetchAPI('crypto', '/cryptocurrency/quotes/latest', {
        params: { symbol }
      });

      const data = response.data[symbol];
      if (!data) {
        return message.reply('Could not find that cryptocurrency!');
      }

      const quote = data.quote.USD;
      const embed = new EmbedBuilder()
        .setTitle(`${data.name} (${symbol})`)
        .setDescription(`Rank: #${data.cmc_rank}`)
        .addFields([
          { name: 'Price', value: `$${quote.price.toFixed(2)}`, inline: true },
          { name: '24h Change', value: `${quote.percent_change_24h.toFixed(2)}%`, inline: true },
          { name: 'Market Cap', value: `$${(quote.market_cap / 1e9).toFixed(2)}B`, inline: true },
          { name: 'Volume (24h)', value: `$${(quote.volume_24h / 1e6).toFixed(2)}M`, inline: true },
          { name: 'Circulating Supply', value: `${(data.circulating_supply / 1e6).toFixed(2)}M ${symbol}`, inline: true }
        ])
        .setColor(quote.percent_change_24h >= 0 ? '#00ff00' : '#ff0000')
        .setFooter({ text: `Last Updated: ${new Date(quote.last_updated).toLocaleString()} | Calls remaining: ${rateCheck.remaining}` })
        .setTimestamp();

      cache.set(symbol, embed);
      message.channel.send({ embeds: [embed] });
    } catch (error) {
      console.error(error);
      message.reply('There was an error fetching the cryptocurrency data. Please try again later.');
    }
  },
};
