const { EmbedBuilder } = require('discord.js');

/**
 * Creates a standardized embed with consistent styling
 * @param {string} title - Embed title
 * @param {string} description - Embed description
 * @param {string} [color='#2b2d31'] - Hex color code
 */
function createEmbed(title, description, color = '#2b2d31') {
    return new EmbedBuilder()
        .setTitle(title)
        .setDescription(description)
        .setColor(color)
        .setTimestamp();
}

module.exports = { createEmbed };

