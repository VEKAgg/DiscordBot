const { SlashCommandBuilder, EmbedBuilder } = require('discord.js');

module.exports = {
  name: 'banner',
  description: "Show a user's banner",
  category: 'utility',
  contributor: 'Sleepless',
  slashCommand: new SlashCommandBuilder()
    .setName('banner')
    .setDescription("Show a user's banner")
    .addUserOption(option =>
      option.setName('user')
        .setDescription('User to get banner from')
        .setRequired(false)),

  async execute(interaction) {
    const isSlash = interaction.commandName !== undefined;
    const target = isSlash
      ? interaction.options.getUser('user') || interaction.user
      : interaction.mentions.users.first() || interaction.author;

    try {
      const user = await target.fetch();
      const bannerURL = user.bannerURL({ size: 4096 });

      if (!bannerURL) {
        const reply = { content: 'This user does not have a banner.', ephemeral: true };
        return isSlash ? interaction.reply(reply) : interaction.reply(reply.content);
      }

      const embed = new EmbedBuilder()
        .setTitle(`${user.username}'s Banner`)
        .setImage(bannerURL)
        .setColor('#0099ff')
        .setAuthor({
          name: isSlash ? interaction.user.tag : interaction.author.tag,
          iconURL: isSlash ? interaction.user.displayAvatarURL({ dynamic: true }) 
            : interaction.author.displayAvatarURL({ dynamic: true })
        })
        .setFooter({
          text: `Contributor: ${module.exports.contributor} • VEKA`,
          iconURL: interaction.client.user.displayAvatarURL()
        })
        .setTimestamp();

      const reply = { embeds: [embed] };
      if (isSlash) {
        await interaction.reply(reply);
      } else {
        await interaction.channel.send(reply);
      }
    } catch (error) {
      logger.error('Banner Command Error:', error);
      const reply = { content: 'Failed to fetch banner.', ephemeral: true };
      if (isSlash) {
        await interaction.reply(reply);
      } else {
        await interaction.reply(reply.content);
      }
    }
  }
};
