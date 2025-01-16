const { EmbedBuilder } = require('discord.js');

module.exports = {
  name: 'weather',
  description: 'Fetch weather information for a specific city (currently disabled).',
  execute(message, args) {
    message.channel.send(
      "Weather functionality is temporarily disabled. Please try again later."
    );
  },
};
