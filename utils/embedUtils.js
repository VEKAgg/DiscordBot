const { EmbedBuilder, Colors } = require('discord.js');

/**
 * Utility function to create a standard embed.
 * @param {string} title - The title of the embed.
 * @param {string} description - The description of the embed.
 * @param {string} color - The color of the embed. Defaults to Colors.Blurple.
 * @returns {EmbedBuilder} - The created embed object.
 */
function createEmbed(title, description, color = Colors.Blurple) {
  return new EmbedBuilder()
    .setTitle(title)
    .setDescription(description)
    .setColor(color);
}

module.exports = { createEmbed };
