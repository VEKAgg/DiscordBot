const { EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'invite',
    description: 'Get bot and server invite links',
    async execute(message) {
        try {
            // Create a permanent invite for the server
            const invite = await message.channel.createInvite({
                maxAge: 0,
                maxUses: 0,
                unique: true,
                reason: 'Created by bot for invite command'
            });

            const embed = new EmbedBuilder()
                .setTitle('🔗 VEKA Bot Invites')
                .setDescription('Join our community or add the bot to your server!')
                .addFields([
                    { 
                        name: 'Bot Invite', 
                        value: `[Click here](https://discord.com/oauth2/authorize?client_id=${message.client.user.id}&scope=bot&permissions=8)` 
                    },
                    { 
                        name: 'Server Invite', 
                        value: `[Click here](${invite.url})` 
                    }
                ])
                .setColor('#FFA500')
                .setTimestamp();

            message.channel.send({ embeds: [embed] });
        } catch (error) {
            console.error('Error creating invite:', error);
            message.reply('Failed to generate invite links.');
        }
    }
};
