const { getModel } = require('../database');
const { logger } = require('../utils/logger');

module.exports = {
    name: 'messageCreate',
    async execute(message, client) {
        if (message.author.bot) return; // Ignore bot messages

        const prefix = '#'; // Define your bot's prefix
        if (!message.content.startsWith(prefix)) return; // Ignore non-prefixed messages

        const args = message.content.slice(prefix.length).trim().split(/ +/);
        const commandName = args.shift().toLowerCase();

        const command = client.commands.get(commandName);
        if (!command) return; // If the command doesn't exist, ignore

        const startTime = Date.now();
        
        try {
            await command.execute(message, args, client);
            client.lastCommandTime = Date.now();
            
            // Log successful command execution
            const CommandLog = getModel('CommandLog');
            await CommandLog.create({
                commandName: command.name,
                userId: message.author.id,
                guildId: message.guild?.id,
                args: args,
                executionTime: Date.now() - startTime,
                status: 'success'
            });

            // Award points
            const userId = message.author.id;
            const points = client.points.get(userId) || 0;
            client.points.set(userId, points + 1);

            // Example: Show points on #points command
            if (message.content === '#points') {
                const embed = {
                    title: 'Your Points',
                    description: `You have ${client.points.get(userId) || 0} points.`,
                    color: 0xFFA500, // Orange
                };
                message.channel.send({ embeds: [embed] });
            }

        } catch (error) {
            logger.error(`Command execution error: ${error}`);
            message.reply('There was an error executing that command!');
            
            // Log failed command execution
            const CommandLog = getModel('CommandLog');
            await CommandLog.create({
                commandName: command.name,
                userId: message.author.id,
                guildId: message.guild?.id,
                args: args,
                executionTime: Date.now() - startTime,
                status: 'error',
                errorMessage: error.message
            });
        }
    },
};
