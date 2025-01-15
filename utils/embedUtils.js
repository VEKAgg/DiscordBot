const { EmbedBuilder } = require('discord.js');

function createEmbed(title, description, color = 0xFFA500) {
    const embed = new EmbedBuilder()
        .setTitle(title)
        .setDescription(description)
        .setColor(color);
    return embed;
}

module.exports = { createEmbed };
