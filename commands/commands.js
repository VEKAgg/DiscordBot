const { EmbedBuilder } = require('discord.js');
const { createEmbed } = require('../utils/embedUtils');

const fs = require('fs');
const path = require('path');

module.exports = {
  name: 'commands',
  description: 'List all available commands.',
  execute(message) {
    const commandDirs = ['./commands/utility', './commands/fun', './commands/informational'];
    let allCommands = '';

    commandDirs.forEach((dir) => {
      const files = fs.readdirSync(path.resolve(__dirname, '..', dir.split('/').pop()));
      const category = dir.split('/').pop().toUpperCase();
      allCommands += `**${category} Commands**\n`;
      files.forEach((file) => {
        const command = require(path.join(__dirname, '..', dir.split('/').pop(), file));
        allCommands += `\`#${command.name}\` - ${command.description}\n`;
      });
      allCommands += '\n';
    });

    const embed = new EmbedBuilder()
      .setTitle('Available Commands')
      .setDescription(allCommands)
      .setColor('BLUE');

    message.channel.send({ embeds: [embed] });
  },
};
