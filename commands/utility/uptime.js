const { createEmbed } = require('../../utils/embedUtils');
const moment = require('moment');

module.exports = {
    name: 'uptime',
    description: 'Show how long the bot has been online.',
    execute(message, args, client) {
        const uptime = moment.duration(client.uptime);
        const embed = createEmbed(
            'Bot Uptime',
            `Online for: **${uptime.days()}d ${uptime.hours()}h ${uptime.minutes()}m ${uptime.seconds()}s**`,
        );
        message.channel.send({ embeds: [embed] });
    },
};
