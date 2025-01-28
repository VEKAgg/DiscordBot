const { createEmbed } = require('../../utils/embedCreator');
const { logger } = require('../../utils/logger');
const ms = require('ms');

module.exports = {
    name: 'remindme',
    description: 'Set a reminder',
    contributor: 'Sleepless',
    execute(message, args) {
        if (args.length < 2) {
            return message.reply('Please provide time and reminder text. Example: `#remindme 1h check email`');
        }

        const timeArg = args[0].toLowerCase();
        const reminderText = args.slice(1).join(' ');

        if (!timeArg.match(/^\d+[smhd]$/)) {
            return message.reply('Invalid time format! Use format like: 30s, 5m, 2h, 1d');
        }

        const duration = ms(timeArg);
        if (!duration || duration < 1000 || duration > 2592000000) { // Between 1 second and 30 days
            return message.reply('Please specify a time between 1 second and 30 days!');
        }

        const embed = createEmbed({
            title: '⏰ Reminder Set',
            description: `I'll remind you about: "${reminderText}"`,
            color: '#FF69B4',
            fields: [
                { name: 'Time', value: timeArg, inline: true },
                { name: 'Reminder will trigger at', value: `<t:${Math.floor((Date.now() + duration) / 1000)}:R>`, inline: true }
            ],
            author: {
                name: message.author.tag,
                iconURL: message.author.displayAvatarURL({ dynamic: true })
            },
            footer: {
                text: `Contributor: ${module.exports.contributor} • VEKA`,
                iconURL: message.client.user.displayAvatarURL()
            }
        });

        message.channel.send({ embeds: [embed] });

        setTimeout(() => {
            const reminderEmbed = createEmbed({
                title: '⏰ Reminder!',
                description: reminderText,
                color: '#FF69B4',
                fields: [
                    { name: 'Set', value: `<t:${Math.floor((Date.now() - duration) / 1000)}:R>`, inline: true }
                ],
                author: {
                    name: message.author.tag,
                    iconURL: message.author.displayAvatarURL({ dynamic: true })
                },
                footer: {
                    text: `Contributor: ${module.exports.contributor} • VEKA`,
                    iconURL: message.client.user.displayAvatarURL()
                }
            });

            message.author.send({ embeds: [reminderEmbed] }).catch(error => {
                logger.error('Failed to send reminder DM:', error);
                message.channel.send({ content: `<@${message.author.id}>`, embeds: [reminderEmbed] });
            });
        }, duration);
    }
};