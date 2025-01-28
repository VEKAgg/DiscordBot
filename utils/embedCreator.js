const { EmbedBuilder } = require('discord.js');

function createEmbed(options = {}) {
    const embed = new EmbedBuilder();
    
    if (options.title) embed.setTitle(options.title);
    if (options.description) embed.setDescription(options.description);
    if (options.color) embed.setColor(options.color);
    if (options.fields) embed.addFields(options.fields);
    if (options.thumbnail) embed.setThumbnail(options.thumbnail);
    if (options.image) embed.setImage(options.image.url);
    if (options.author) embed.setAuthor(options.author);
    if (options.footer) embed.setFooter(options.footer);
    if (options.timestamp) embed.setTimestamp();

    return embed;
}

module.exports = { createEmbed };
