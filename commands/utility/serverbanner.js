const { createEmbed } = require('../../utils/embedCreator');

module.exports = {
  name: 'serverbanner',
  description: 'Display the server banner.',
  contributor: 'Sleepless',
  async execute(message) {
    const bannerUrl = message.guild.bannerURL({ size: 4096, format: 'png', dynamic: true });

    if (!bannerUrl) {
      return message.reply('This server does not have a banner set.');
    }

    const embed = createEmbed({
      title: `${message.guild.name} Server Banner`,
      image: { url: bannerUrl },
      author: {
        name: message.author.tag,
        iconURL: message.author.displayAvatarURL({ dynamic: true })
      },
      footer: {
        text: `Contributor: ${module.exports.contributor} • VEKA`,
        iconURL: message.client.user.displayAvatarURL()
      }
    });

    message.channel.send({ embeds: [embed] });
  },
};
