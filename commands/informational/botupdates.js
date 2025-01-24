const { EmbedBuilder } = require('discord.js');
const { fetchAPI } = require('../../utils/apiManager');

module.exports = {
    name: 'botupdates',
    description: 'Show recent bot updates',
    async execute(message) {
        try {
            const commits = await fetchAPI('github', '/repos/VEKAgg/DiscordBot/commits')
                .catch(() => null);
            
            if (!commits) {
                return message.reply('Unable to fetch updates. Please try again later.');
            }

            const embed = new EmbedBuilder()
                .setTitle('🤖 Recent Bot Updates')
                .setDescription(
                    commits.slice(0, 5).map(commit => 
                        `• ${commit.commit.message.split('\n')[0]}`
                    ).join('\n') || 'No recent updates'
                )
                .setColor('#0099ff')
                .setTimestamp();

            message.channel.send({ embeds: [embed] });
        } catch (error) {
            console.error('Bot Updates Error:', error);
            message.reply('Unable to fetch updates at this time.');
        }
    }
};
