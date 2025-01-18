const { EmbedBuilder } = require('discord.js');

function createEmbed(options = {}) {
    const embed = new EmbedBuilder()
        .setColor(options.color || '#FFA500') // Default color if not provided
        .setTimestamp();

    // Support old usage pattern where options is a string
    if (typeof options === 'string') {
        return embed.setDescription(options);
    }

    // Set optional fields if provided
    if (options.title) embed.setTitle(options.title);
    if (options.description) embed.setDescription(options.description);
    if (options.fields && Array.isArray(options.fields)) {
        embed.addFields(options.fields);
    }
    if (options.footer) {
        // Validate footer structure
        if (typeof options.footer === 'string') {
            embed.setFooter({ text: options.footer });
        } else if (typeof options.footer === 'object' && options.footer.text) {
            embed.setFooter({ 
                text: options.footer.text, 
                iconURL: options.footer.iconURL || undefined 
            });
        } else {
            console.warn('Invalid footer format:', options.footer);
        }
    }

    return embed;
}

module.exports = { createEmbed };
