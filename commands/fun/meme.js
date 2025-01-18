const { createEmbed } = require('../../utils/embedCreator');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const NodeCache = require('node-cache');
const { logger } = require('../../utils/logger');
const cache = new NodeCache({ stdTTL: 600 }); // Cache for 10 minutes

const subreddits = {
    dank: { name: 'dankmemes', emoji: '🔥', description: 'Dank memes' },
    wholesome: { name: 'wholesomememes', emoji: '💖', description: 'Wholesome memes' },
    me_irl: { name: 'me_irl', emoji: '🤳', description: 'Relatable memes' },
    memes: { name: 'memes', emoji: '😂', description: 'General memes' },
    random: { emoji: '🎲', description: 'Random from all meme subreddits' }
};

module.exports = {
    name: 'meme',
    description: 'Get a random meme from Reddit',
    contributor: 'Sleepless',
    async execute(message, args) {
        const category = args[0]?.toLowerCase();

        if (category && !subreddits[category]) {
            const categoryList = Object.entries(subreddits)
                .map(([name, info]) => `${info.emoji} **${name}** - ${info.description}`)
                .join('\n');
            return message.reply(`Invalid category! Available categories:\n${categoryList}`);
        }

        const rateCheck = await rateLimiter.checkLimit('meme');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        try {
            const subreddit = category ? subreddits[category].name : 'random';
            const meme = await fetchAPI('reddit', `/r/${subreddit}/random`);

            if (!meme?.data?.children?.length) {
                return message.reply('Failed to fetch meme. Please try again.');
            }

            const post = meme.data.children[0].data;
            const { emoji } = subreddits[category || 'random'];

            const embed = createEmbed({
                title: `${emoji} ${post.title}`,
                url: `https://reddit.com${post.permalink}`,
                image: { url: post.url },
                color: '#FF4500',
                fields: [
                    { name: 'Author', value: `u/${post.author}`, inline: true },
                    { name: 'Subreddit', value: `r/${post.subreddit}`, inline: true },
                    { name: 'Stats', value: `👍 ${post.ups} | 💬 ${post.num_comments}`, inline: true }
                ],
                author: {
                    name: message.author.tag,
                    iconURL: message.author.displayAvatarURL({ dynamic: true })
                },
                footer: {
                    text: `Contributor: ${module.exports.contributor} • VEKA | Category: ${category || 'Random'}`,
                    iconURL: message.client.user.displayAvatarURL()
                }
            });

            cache.set(`meme_${category || 'random'}`, embed);
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            logger.error('Meme Error:', error);
            message.reply('Failed to fetch meme. Please try again later.');
        }
    }
};
