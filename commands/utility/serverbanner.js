const { SlashCommandBuilder, EmbedBuilder } = require('discord.js');

module.exports = {
  name: 'serverbanner',
  description: 'Display the server banner',
  category: 'utility',
  contributor: 'Sleepless',
  slashCommand: new SlashCommandBuilder()
    .setName('serverbanner')
    .setDescription('Display the server banner'),

  async execute(interaction) {
    const isSlash = interaction.commandName !== undefined;
    const guild = isSlash ? interaction.guild : interaction.guild;
    
    try {
      const bannerUrl = guild.bannerURL({ size: 4096, format: 'png', dynamic: true });

      if (!bannerUrl) {
        const reply = { 
          content: 'This server does not have a banner set.',
          ephemeral: true 
        };
        return isSlash ? interaction.reply(reply) : interaction.reply(reply.content);
      }

      const embed = new EmbedBuilder()
        .setTitle(`${guild.name} Server Banner`)
        .setImage(bannerUrl)
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
      logger.error('Server Banner Command Error:', error);
      const reply = { 
        content: 'Failed to fetch server banner.',
        ephemeral: true 
      };
      if (isSlash) {
        await interaction.reply(reply);
      } else {
        await interaction.reply(reply.content);
      }
    }
  }
};
