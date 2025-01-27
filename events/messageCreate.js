const { User } = require('../database');
const { logger } = require('../utils/logger');
const { XPManager } = require('../utils/xpManager');
const { ErrorHandler } = require('../utils/errorHandler');

module.exports = {
    name: 'messageCreate',
    async execute(message) {
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
        } catch (error) {
            logger.error('Message create error:', error);
            await ErrorHandler.sendErrorMessage(message, { message: 'An error occurred while executing the command.' });
        }
    }
};

