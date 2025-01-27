const { GuildAnalytics, User, CommandLog, WelcomeStats } = require('../../database');
const mongoose = require('mongoose');

module.exports = {
    name: 'dbtest',
    description: 'Test database connectivity and records',
    async execute(message) {
        if (!message.member.permissions.has('Administrator')) {
            return message.reply('Only administrators can use this command.');
        }

        try {
            // Test 1: Check connection status
            const connectionState = mongoose.connection.readyState;
            const states = {
                0: '❌ Disconnected',
                1: '✅ Connected',
                2: '🔄 Connecting',
                3: '🔄 Disconnecting'
            };

            let response = `**MongoDB Status**: ${states[connectionState]}\n\n`;

            // Test 2: Check collections
            const collections = {
                'Users': await User.countDocuments(),
                'Guild Analytics': await GuildAnalytics.countDocuments(),
                'Command Logs': await CommandLog.countDocuments(),
                'Welcome Stats': await WelcomeStats.countDocuments()
            };

            response += '**Collection Records**:\n';
            for (const [name, count] of Object.entries(collections)) {
                response += `${name}: ${count} records\n`;
            }

            // Test 3: Write test record
            const testLog = await CommandLog.create({
                guildId: message.guild.id,
                userId: message.author.id,
                commandName: 'dbtest',
                timestamp: new Date()
            });

            response += '\n✅ Successfully wrote test record to CommandLog';

            message.channel.send(response);
        } catch (error) {
            message.channel.send(`❌ Database Error: ${error.message}`);
        }
    }
}; 