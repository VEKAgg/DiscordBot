const { EmbedBuilder } = require('discord.js');

module.exports = {
  name: 'wiki',
  description: 'Fetch a summary from Wikipedia.',
  execute(message, args) {
    if (!args.length) {
      return message.channel.send('Please provide a topic. Example: `#wiki technology`');
    }
    const topic = args.join(' ');
    // Placeholder Wikipedia summary
    const summary = `This is a brief summary about ${topic}. Visit Wikipedia for more details.`;
    const embed = new EmbedBuilder()
      .setTitle(`Wikipedia: ${topic}`)
      .setDescription(summary)
      .setColor('AQUA');
    message.channel.send({ embeds: [embed] });
  },
};
