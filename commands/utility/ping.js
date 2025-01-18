const { createEmbed } = require('../../utils/embedCreator');

module.exports = {
    name: 'ping',
    description: 'Check bot latency',
    contributor: 'Sleepless',
    async execute(message) {
        try {
            const sent = await message.channel.send('Pinging...');
            const latency = sent.createdTimestamp - message.createdTimestamp;
            const apiLatency = Math.round(message.client.ws.ping);

            const embed = createEmbed({
                title: '🏓 Pong!',
                fields: [
                    { name: 'Bot Latency', value: `${latency}ms`, inline: true },
                    { name: 'API Latency', value: `${apiLatency}ms`, inline: true }
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

            await sent.edit({ content: null, embeds: [embed] });
        } catch (error) {
            message.reply('Error checking ping. Please try again.');
        }
    },
}; 