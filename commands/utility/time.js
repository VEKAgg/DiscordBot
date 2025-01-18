const embedUtils = require('../../utils/embedUtils');
const moment = require('moment-timezone');

module.exports = {
    name: 'time',
    description: 'Displays the current time in a specific timezone.',
    execute(message, args, client) {
        const timezone = args[0] || 'UTC';
        try {
            const time = moment().tz(timezone).format('MMMM Do YYYY, h:mm:ss a');
            const embed = createEmbed('Current Time', `Time in ${timezone}:\n**${time}**`);
            message.channel.send({ embeds: [embed] });
        } catch (err) {
            message.reply('Invalid timezone. Please use a valid timezone, like `America/New_York`.');
        }
    },
};
