const { createEmbed } = require('../utils/embedUtils');

module.exports = {
    name: 'remindme',
    description: 'Sets a reminder.',
    execute(message, args) {
        const time = parseInt(args[0], 10); // Time in seconds
        const reminder = args.slice(1).join(' ');

        if (!time || !reminder) {
            const embed = createEmbed('Error', 'Usage: #remindme <time_in_seconds> <reminder_message>', 0xFF0000); // Red for error
            return message.channel.send({ embeds: [embed] });
        }

        const embed = createEmbed('Reminder Set', `I'll remind you in ${time} seconds!`);
        message.channel.send({ embeds: [embed] });

        setTimeout(() => {
            const reminderEmbed = createEmbed('Reminder', reminder);
            message.reply({ embeds: [reminderEmbed] });
        }, time * 1000);
    },
};

