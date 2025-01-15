const { EmbedBuilder } = require('discord.js');

// Default embed color
const DEFAULT_COLOR = 0xFFA500; // Orange

module.exports = {
    createEmbed(title, description, color = DEFAULT_COLOR) {
        return new EmbedBuilder()
            .setTitle(title)
            .setDescription(description)
            .setColor(color);
    },
};
