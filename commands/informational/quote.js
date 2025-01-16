const { EmbedBuilder } = require('discord.js');

module.exports = {
  name: 'quote',
  description: 'Fetch a quote based on author or keyword.',
  execute(message, args) {
    if (!args.length) {
      return message.channel.send('Please provide an author or keyword. Example: `#quote life`');
    }
    const keyword = args.join(' ');
    // Placeholder quote
    const quote = `"Life is what happens when you're busy making other plans." - John Lennon`;
    const embed = new EmbedBuilder()
      .setTitle(`Quote for: ${keyword}`)
      .setDescription(quote)
      .setColor('PURPLE');
    message.channel.send({ embeds: [embed] });
  },
};
