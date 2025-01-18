const embedUtils = require('../../utils/embedUtils');

module.exports = {
  name: 'serverbanner',
  description: 'Display the server banner.',
  async execute(message) {
    const bannerUrl = message.guild.bannerURL({ size: 2048, format: 'png', dynamic: true });

    if (!bannerUrl) {
      return message.reply('This server does not have a banner set.');
    }

    const embed = new EmbedBuilder()
      .setTitle(`${message.guild.name} Server Banner`)
      .setImage(bannerUrl)
      .setColor('BLUE');

    message.channel.send({ embeds: [embed] });
  },
};
