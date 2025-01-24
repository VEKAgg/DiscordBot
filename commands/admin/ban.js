const { EmbedBuilder, PermissionFlagsBits } = require('discord.js');

module.exports = {
    name: 'ban',
    description: 'Ban a user from the server',
    permissions: [PermissionFlagsBits.BanMembers],
    async execute(message, args) {
        const user = message.mentions.users.first();
        if (!user) return message.reply('Please mention a user to ban.');

        try {
            await message.guild.members.ban(user);
            const embed = new EmbedBuilder()
                .setTitle('🔨 User Banned')
                .setDescription(`${user.tag} has been banned from the server.`)
                .setColor('#ff0000') // Red for errors
                .setTimestamp();
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            console.error('Ban Error:', error);
            message.reply('Failed to ban the user.');
        }
    }
};
