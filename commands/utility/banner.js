const { SlashCommandBuilder, EmbedBuilder } = require('discord.js');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
  name: 'banner',
  description: "Show a user's banner",
  category: 'utility',
  contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
  slashCommand: new SlashCommandBuilder()
    .setName('banner')
    .setDescription("Show a user's banner")
    .addUserOption(option =>
      option.setName('user')
        .setDescription('User to get banner from')
        .setRequired(false)),

  async execute(interaction) {
    const targetUser = interaction.options.getUser('user') || interaction.user;
    const fetchedUser = await interaction.client.users.fetch(targetUser.id, { force: true });

    if (!fetchedUser.banner) {
      return interaction.reply({
        content: 'This user does not have a banner!',
        ephemeral: true
      });
    }

    const embed = new EmbedBuilder()
      .setTitle(`${fetchedUser.tag}'s Banner`)
      .setColor('#2B2D31')
      .setImage(fetchedUser.bannerURL({ size: 4096, dynamic: true }))
      .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

    await interaction.reply({ embeds: [embed] });
  }
};
