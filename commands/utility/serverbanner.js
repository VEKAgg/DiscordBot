const { SlashCommandBuilder, EmbedBuilder } = require('discord.js');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
  name: 'serverbanner',
  description: 'Display the server banner',
  category: 'utility',
  contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
  slashCommand: new SlashCommandBuilder()
    .setName('serverbanner')
    .setDescription('Display the server banner'),

  async execute(interaction) {
    const guild = interaction.guild;
    
    if (!guild.banner) {
      return interaction.reply({
        content: 'This server does not have a banner!',
        ephemeral: true
      });
    }

    const embed = new EmbedBuilder()
      .setTitle(`${guild.name}'s Banner`)
      .setColor('#2B2D31')
      .setImage(guild.bannerURL({ size: 4096 }))
      .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

    await interaction.reply({ embeds: [embed] });
  }
};
