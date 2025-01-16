const { EmbedBuilder } = require('discord.js');

module.exports = {
  name: 'news',
  description: 'Fetch the latest news headlines.',
  execute(message, args) {
    const topic = args.length ? args.join(' ') : 'general';
    // Placeholder news
    const headlines = [
      `Breaking News: Major event happening in ${topic}!`,
      `Headline 2 about ${topic}`,
      `Headline 3 about ${topic}`,
    ];
    const embed = new EmbedBuilder()
      .setTitle(`Latest News on: ${topic}`)
      .setDescription(headlines.join('\n'))
      .setColor('ORANGE');
    message.channel.send({ embeds: [embed] });
  },
};
