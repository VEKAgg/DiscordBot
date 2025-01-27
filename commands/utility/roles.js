const { EmbedBuilder } = require('discord.js');
const { UTILITY } = require('../../utils/embedColors');
const ErrorHandler = require('../../utils/errorHandler');

module.exports = {
    name: 'roles',
    description: 'Display server roles',
    async execute(message) {
        try {
            const roles = message.guild.roles.cache
                .sort((a, b) => b.position - a.position)
                .map(role => role.toString())
                .join(', ');

            const embed = new EmbedBuilder()
                .setTitle('Server Roles')
                .setDescription(roles)
                .setColor(UTILITY)
                .setTimestamp();

            await message.channel.send({ embeds: [embed] });
        } catch (error) {
            await ErrorHandler.sendErrorMessage(message, error);
        }
    }
};
