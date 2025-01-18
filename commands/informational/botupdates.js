const { EmbedBuilder } = require('discord.js');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const NodeCache = require('node-cache');
const cache = new NodeCache({ stdTTL: 3600 }); // Cache for 1 hour

module.exports = {
    name: 'botupdates',
    description: 'Show the latest updates from GitHub repository',
    async execute(message) {
        const cacheKey = 'github_updates';
        const cachedUpdates = cache.get(cacheKey);

        if (cachedUpdates) {
            message.channel.send({ embeds: [cachedUpdates] });
            return;
        }

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

            const embed = new EmbedBuilder()
                .setTitle('🤖 Bot Updates')
                .setDescription('Latest changes from GitHub:')
                .addFields([
                    { name: 'Recent Updates', value: updateText || 'No recent updates' },
                    { name: 'Repository', value: `[View on GitHub](${repo.html_url})` },
                    { name: 'Stats', value: `⭐ ${repo.stargazers_count} | 🔄 ${repo.forks_count}` }
                ])
                .setColor('#2b2d31')
                .setFooter({ text: `Last updated: ${new Date().toLocaleDateString()}` })
                .setTimestamp();

            cache.set(cacheKey, embed);
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            console.error('GitHub API Error:', error);
            message.reply('Failed to fetch updates. Please try again later.');
        }
    },
};
