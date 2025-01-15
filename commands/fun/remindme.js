const { createEmbed } = require('../../utils/embedUtils');

module.exports = {
    name: 'remindme',
    description: 'Sets a reminder with time units (e.g., 1h30m).',
    execute(message, args) {
        const timeRegex = /(\d+)([smhd])/g;
        const reminderText = args.join(' ').replace(timeRegex, '').trim();

        if (!reminderText) {
            const embed = createEmbed('Error', 'Usage: #remindme <time> <message>', 0xFF0000);
            return message.channel.send({ embeds: [embed] });
        }

        let totalMs = 0;
        let match;
        while ((match = timeRegex.exec(args.join(' '))) !== null) {
            const [_, value, unit] = match;
            const msPerUnit = { s: 1000, m: 60000, h: 3600000, d: 86400000 };
            totalMs += parseInt(value, 10) * msPerUnit[unit];
        }

        const embed = createEmbed('Reminder Set', `I'll remind you in ${args.join(' ')}.`);
        message.channel.send({ embeds: [embed] });

        setTimeout(() => {
            const reminderEmbed = createEmbed('Reminder', reminderText);
            message.reply({ embeds: [reminderEmbed] });
        }, totalMs);
    },
};
