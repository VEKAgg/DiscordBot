const { EmbedBuilder } = require('discord.js');

/**
 * Creates a standardized embed with the given title and description
 * @param {string} title - The embed title
 * @param {string} description - The embed description
 * @param {string} [color='#2b2d31'] - Hex color code for the embed
 * @returns {EmbedBuilder} The created embed
 */
function createEmbed(title, description, color = '#2b2d31') {
    return new EmbedBuilder()
        .setTitle(title)
        .setDescription(description)
        .setColor(color)
        .setTimestamp();
}

module.exports = {
    createEmbed
};

