const { EmbedBuilder } = require('discord.js');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const NodeCache = require('node-cache');
const cache = new NodeCache({ stdTTL: 600 }); // Cache for 10 minutes

module.exports = {
  name: 'news',
  description: 'Get latest news headlines with filtering options',
  async execute(message, args) {
    const validCategories = ['business', 'technology', 'science', 'health', 'sports'];
    let category = 'general';
    let country = 'us';
    let query = '';

    // Parse arguments
    args.forEach(arg => {
      if (arg.startsWith('category:') && validCategories.includes(arg.split(':')[1])) {
        category = arg.split(':')[1];
      } else if (arg.startsWith('country:')) {
        country = arg.split(':')[1];
      } else {
        query += arg + ' ';
      }
    });

    const cacheKey = `news_${category}_${country}_${query.trim()}`;
    const cachedNews = cache.get(cacheKey);

    if (cachedNews) {
      message.channel.send({ embeds: [cachedNews] });
      return;
    }

    const rateCheck = await rateLimiter.checkLimit('news');
    if (!rateCheck.success) {
      return message.reply(rateCheck.message);
    }

    try {
      const params = {
        country,
        category,
        pageSize: 5,
        q: query.trim()
      };

      const news = await fetchAPI('news', '/top-headlines', { params });

      if (!news.articles.length) {
        return message.reply('No news found for those criteria!');
      }

      const embed = new EmbedBuilder()
        .setTitle(`📰 Latest ${category.charAt(0).toUpperCase() + category.slice(1)} News`)
        .setDescription(query ? `Search: "${query.trim()}"` : '')
        .setColor('#0099ff')
        .setFooter({ text: `Country: ${country.toUpperCase()} | Calls remaining: ${rateCheck.remaining}` })
        .setTimestamp();

      news.articles.forEach((article, index) => {
        embed.addFields([{
          name: `${index + 1}. ${article.title}`,
          value: `${article.description || 'No description available'}\n[Read More](${article.url})`
        }]);
      });

      cache.set(cacheKey, embed);
      message.channel.send({ embeds: [embed] });
    } catch (error) {
      console.error('News API Error:', error);
      message.reply('Error fetching news! Please try again later.');
    }
  },
};
