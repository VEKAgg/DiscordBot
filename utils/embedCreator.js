const { EmbedBuilder } = require('discord.js');

function createEmbed(options = {}) {
    const embed = new EmbedBuilder()
        .setColor(options.color || '#FFA500')
        .setTimestamp();
        
    if (typeof options === 'string') {
        // Support old usage pattern
        return embed.setDescription(options);
    }
    
    if (options.title) embed.setTitle(options.title);
    if (options.description) embed.setDescription(options.description);
    if (options.fields) embed.addFields(options.fields);
    if (options.footer) {
        embed.setFooter({ 
            text: options.footer,
            iconURL: options.footerIcon 
        });
    }
    
    return embed;
}

module.exports = { createEmbed }; 