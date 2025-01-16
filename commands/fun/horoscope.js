const { EmbedBuilder } = require('discord.js');

module.exports = {
  name: 'horoscope',
  description: 'Fetch today’s horoscope for a given zodiac sign.',
  execute(message, args) {
    if (!args[0]) {
      return message.channel.send('Please provide a zodiac sign. Example: `#horoscope aries`');
    }
    const sign = args[0].toLowerCase();
    // Placeholder horoscope
    const horoscope = `Today is a great day for ${sign}! Stars are aligned in your favor.`;
    const embed = new EmbedBuilder()
      .setTitle(`Horoscope for ${sign.charAt(0).toUpperCase() + sign.slice(1)}`)
      .setDescription(horoscope)
      .setColor('BLUE');
    message.channel.send({ embeds: [embed] });
  },
};
