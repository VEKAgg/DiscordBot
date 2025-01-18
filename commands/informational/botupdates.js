const { createEmbed } = require('../../utils/embedCreator');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const NodeCache = require('node-cache');
const { logger } = require('../../utils/logger');
const cache = new NodeCache({ stdTTL: 3600 }); // Cache for 1 hour

module.exports = {
    name: 'botupdates',
    description: 'Show the latest updates from GitHub repository',
    contributor: 'Sleepless',
    async execute(message) {
        const rateCheck = await rateLimiter.checkLimit('github');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        try {
            const [commits, repo] = await Promise.all([
                fetchAPI('github', '/repos/VEKAgg/DiscordBot/commits'),
                fetchAPI('github', '/repos/VEKAgg/DiscordBot')
            ]);

            const latestCommits = commits.slice(0, 5);
            let updateText = '';

            latestCommits.forEach(commit => {
                updateText += `• ${commit.commit.message}\n`;
            });

            const embed = createEmbed({
                title: '🤖 Bot Updates',
                description: 'Latest changes from GitHub:',
                fields: [
                    { name: 'Recent Updates', value: updateText || 'No recent updates' },
                    { name: 'Repository', value: `[View on GitHub](${repo.html_url})` },
                    { name: 'Stats', value: `⭐ ${repo.stargazers_count} | 🔄 ${repo.forks_count}` }
                ],
                color: '#2b2d31',
                author: {
                    name: message.author.tag,
                    iconURL: message.author.displayAvatarURL({ dynamic: true })
                },
                footer: {
                    text: `Contributor: ${module.exports.contributor} • VEKA | Last updated: ${new Date().toLocaleDateString()}`,
                    iconURL: message.client.user.displayAvatarURL()
                }
            });

            cache.set('github_updates', embed);
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            logger.error('Error in botupdates command:', error);
            message.reply('Failed to fetch updates. Please try again later.');
        }
    }
};
