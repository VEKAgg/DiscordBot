const { EmbedBuilder } = require('discord.js');

class ErrorHandler {
    static async sendErrorMessage(message, error) {
        const errorEmbed = new EmbedBuilder()
            .setDescription(`❌ ${error.message || 'An error occurred'}`)
            .setColor('#FF0000');
        
        return message.reply({ embeds: [errorEmbed], ephemeral: true });
    }
}

module.exports = ErrorHandler; 