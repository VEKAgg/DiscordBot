const { EmbedBuilder } = require('discord.js');

module.exports = {
  name: 'randomcolor',
  description: 'Display a random color and its hex code.',
  execute(message) {
    const randomColor = Math.floor(Math.random() * 16777215).toString(16);
    const hexColor = `#${randomColor}`;

    const embed = new EmbedBuilder()
      .setTitle('Random Color')
      .setDescription(`Hex Code: ${hexColor}`)
      .setColor(hexColor);

    message.channel.send({ embeds: [embed] });
  },
};
