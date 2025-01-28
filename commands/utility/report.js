const { EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'report',
    description: 'Report a user',
    async execute(message, args) {
        const user = message.mentions.users.first();
        const reason = args.slice(1).join(' ') || 'No reason provided';

        if (!user) return message.reply('Please mention a user to report.');

        const reportEmbed = new EmbedBuilder()
            .setTitle('🚨 User Report')
            .addFields([
                { name: 'Reported User', value: user.tag, inline: true },
                { name: 'Reported By', value: message.author.tag, inline: true },
                { name: 'Reason', value: reason }
            ])
            .setColor('#FFA500') // Orange for reports
            .setTimestamp();

        // Send report to a specific channel or log it
        const reportChannel = message.guild.channels.cache.find(ch => ch.name === 'reports');
        if (reportChannel) {
            await reportChannel.send({ embeds: [reportEmbed] });
            message.reply('Your report has been submitted.');
        } else {
            message.reply('Report channel not found.');
        }
    }
};
  