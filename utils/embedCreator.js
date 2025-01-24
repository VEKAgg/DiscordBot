const { EmbedBuilder } = require('discord.js');

function createEmbed({ title, description, fields, color, author, footer, timestamp = true }) {
    const embed = new EmbedBuilder()
        .setTitle(title || '')
        .setColor(color || '#0099ff');

    if (description) embed.setDescription(description);
    if (fields) embed.addFields(fields);
    if (author) embed.setAuthor(author);
    if (footer) embed.setFooter(footer);
    if (timestamp) embed.setTimestamp();

    return embed;
}

module.exports = { createEmbed }; 