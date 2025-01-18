const { createEmbed } = require('../../utils/embedCreator');

module.exports = {
  name: 'banner',
  description: "Show a user's banner.",
  contributor: 'Sleepless',
  args: false,
  async execute(message, args) {
    const user = message.mentions.users.first() || message.author;

    try {
      const userProfile = await user.fetch();
      const bannerUrl = userProfile.bannerURL({ size: 4096, format: 'png', dynamic: true });

      if (!bannerUrl) {
        return message.reply(`${user.username} does not have a banner set.`);
      }

      const embed = createEmbed({
        title: `${user.username}'s Banner`,
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
    } catch (error) {
      logger.error('Banner command error:', error);
      message.reply('Could not fetch the banner. Please try again later.');
    }
  },
};
