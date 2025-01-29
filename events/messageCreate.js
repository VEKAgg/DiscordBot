const { User } = require('../database');
const { logger } = require('../utils/logger');
const { XPManager } = require('../utils/xpManager');
const { ErrorHandler } = require('../utils/errorHandler');
const { massDMUsers } = require('../utils/massDM');

module.exports = {
    name: 'messageCreate',
    async execute(message, client) {
        try {
            if (message.author.bot) return;
            
            // Handle XP
            await XPManager.handleActivity(message.member, 'message');
            
            // Command handling
            const prefix = process.env.PREFIX || '!';
            if (!message.content.startsWith(prefix)) return;
            
            const args = message.content.slice(prefix.length).trim().split(/ +/);
            const commandName = args.shift().toLowerCase();
            
            const command = message.client.commands.get(commandName);
            if (!command) return;
            
            await command.execute(message, args);

            const today = new Date();
            today.setHours(0, 0, 0, 0);

            await User.findOneAndUpdate(
                { 
                    userId: message.author.id,
                    guildId: message.guild.id
                },
                {
                    $inc: { 'messages.daily': 1, 'messages.total': 1 },
                    $set: { 'messages.lastMessageDate': new Date() }
                },
                { upsert: true }
            );

            if (message.content.startsWith('!massdm')) {
                try {
                    const presetMessage = "This is a preset message for all users.";
                    await massDMUsers(client, presetMessage);
                    await message.reply('Mass DM process started.');
                } catch (error) {
                    logger.error('Error in mass DM command:', error);
                    await message.reply('Failed to start mass DM process.');
                }
            }
        } catch (error) {
            logger.error('Message create error:', error);
            await ErrorHandler.sendErrorMessage(message, { message: 'An error occurred while executing the command.' });
        }
    }
};

