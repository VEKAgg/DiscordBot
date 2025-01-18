const { createEmbed } = require('../../utils/embedCreator');
const fs = require('fs');
const path = require('path');
const { logger } = require('../../utils/logger');

module.exports = {
    name: 'commands',
    description: 'List all commands',
    execute(message) {
        try {
            const commandsPath = path.join(__dirname, '..');
            const categories = fs.readdirSync(commandsPath)
                .filter(folder => fs.statSync(path.join(commandsPath, folder)).isDirectory());

            const embed = createEmbed({
                title: 'Available Commands',
                description: 'Here are all available command categories:'
            });

            categories.forEach(category => {
                const commands = fs.readdirSync(path.join(commandsPath, category))
                    .filter(file => file.endsWith('.js'))
                    .map(file => file.replace('.js', ''));
                
                embed.addFields({
                    name: category.charAt(0).toUpperCase() + category.slice(1),
                    value: commands.join(', ') || 'No commands',
                    inline: false
                });
            });

            message.channel.send({ embeds: [embed] });
        } catch (error) {
            logger.error('Error in commands command:', error);
            message.reply('An error occurred while fetching commands.');
        }
    }
};
