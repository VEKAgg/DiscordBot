const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');
const { fetchAPI } = require('../../utils/apiManager');
const { logger } = require('../../utils/logger');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'botupdates',
    description: 'Show recent bot updates',
    category: 'informational',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    slashCommand: new SlashCommandBuilder()
        .setName('botupdates')
        .setDescription('Show recent bot updates and changes'),

    async execute(interaction) {
        try {
            const commits = await fetchAPI('github', '/repos/VEKAgg/DiscordBot/commits')
                .catch(() => null);
            
            if (!commits) {
                return interaction.reply({
                    content: 'Unable to fetch updates. Please try again later.',
                    ephemeral: true
                });
            }

            const embed = new EmbedBuilder()
                .setTitle('🤖 Recent Bot Updates')
                .setDescription(
                    commits.slice(0, 5).map(commit => 
                        `• ${commit.commit.message.split('\n')[0]}`
                    ).join('\n') || 'No recent updates'
                )
                .setColor('#2B2D31')
                .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

            await interaction.reply({ embeds: [embed] });
        } catch (error) {
            logger.error('Bot Updates Error:', error);
            return interaction.reply({
                content: 'Unable to fetch updates at this time.',
                ephemeral: true
            });
        }
    }
};
