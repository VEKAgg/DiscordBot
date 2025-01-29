const { createEmbed } = require('../utils/embedUtils');

module.exports = {
    name: 'schedule',
    description: 'Schedule a message to be sent later.',
    execute(message, args) {
        const time = parseInt(args[0], 10); // Time in seconds
        const announcement = args.slice(1).join(' ');

        if (!time || !announcement) {
            const embed = createEmbed('Error', 'Usage: #schedule <time_in_seconds> <message>', 0xFF0000); // Red for error
            return message.channel.send({ embeds: [embed] });
        }

        const embed = createEmbed('Scheduled Message', `Your message will be sent in ${time} seconds.`);
        message.channel.send({ embeds: [embed] });

        setTimeout(() => {
            const announcementEmbed = createEmbed('Announcement', announcement);
            message.channel.send({ embeds: [announcementEmbed] });
        }, time * 1000);
    },
};
