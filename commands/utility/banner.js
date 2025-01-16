const { EmbedBuilder } = require('discord.js');

module.exports = {
  name: 'banner',
  description: "Show a user's banner.",
  args: false,
  async execute(message, args) {
    const user = message.mentions.users.first() || message.author;

    try {
      const userProfile = await user.fetch();
      const bannerUrl = userProfile.bannerURL({ size: 2048, format: 'png', dynamic: true });

      if (!bannerUrl) {
        return message.reply(`${user.username} does not have a banner set.`);
      }

      const embed = new EmbedBuilder()
        .setTitle(`${user.username}'s Banner`)
        .setImage(bannerUrl)
        .setColor('GREEN');

      message.channel.send({ embeds: [embed] });
    } catch (error) {
      console.error(error);
      message.reply('Could not fetch the banner. Please try again later.');
    }
  },
};
