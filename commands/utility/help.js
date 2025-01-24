const { EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'help',
    description: 'Show important commands',
    async execute(message) {
        const embed = new EmbedBuilder()
            .setTitle('📚 Help')
            .setDescription('Here are some important commands you can use:')
            .addFields([
                { name: '!invite', value: 'Get the bot invite link.' },
                { name: '!botinfo', value: 'Show bot information.' },
                { name: '!analytics', value: 'View server analytics (Admin only).' },
                { name: '!report', value: 'Report a user.' },
                { name: '!ban', value: 'Ban a user (Admin only).' }
            ])
            .setColor('#FFA500') // Orange for help
            .setTimestamp();

        message.channel.send({ embeds: [embed] });
    }
}; 