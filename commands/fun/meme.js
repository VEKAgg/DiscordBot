const { EmbedBuilder } = require('discord.js');
const { fetchAPI } = require('../../utils/apiManager');
const rateLimiter = require('../../utils/rateLimiter');
const NodeCache = require('node-cache');
const cache = new NodeCache({ stdTTL: 300 }); // Cache for 5 minutes

const subredditInfo = {
    memes: { emoji: '😂', color: '#FF4500' },
    dankmemes: { emoji: '💀', color: '#7193FF' },
    wholesomememes: { emoji: '🥰', color: '#FFB6C1' },
    programmerhumor: { emoji: '👨‍💻', color: '#008080' },
    meirl: { emoji: '🤳', color: '#4169E1' },
    funny: { emoji: '🤣', color: '#FFA500' }
};

module.exports = {
    name: 'meme',
    description: 'Fetch a random meme from Reddit',
    async execute(message, args) {
        const subreddit = args[0]?.toLowerCase() || 'memes';
        
        if (!subredditInfo[subreddit]) {
            const validSubs = Object.entries(subredditInfo)
                .map(([name, info]) => `${info.emoji} r/${name}`)
                .join('\n');
            return message.reply(`Invalid subreddit! Available options:\n${validSubs}`);
        }

        const rateCheck = await rateLimiter.checkLimit('meme');
        if (!rateCheck.success) {
            return message.reply(rateCheck.message);
        }

        const cacheKey = `meme_${subreddit}`;
        const cachedMeme = cache.get(cacheKey);

        if (cachedMeme) {
            message.channel.send({ embeds: [cachedMeme] });
            return;
        }

        try {
            const meme = await fetchAPI('reddit', `/r/${subreddit}/random`);
            
            if (!meme?.url || !meme?.title) {
                return message.reply('Failed to fetch meme. Please try again.');
            }

            // Check if URL is a valid image
            if (!/\.(jpg|jpeg|png|gif)$/i.test(meme.url)) {
                return message.reply('Retrieved post is not an image. Please try again.');
            }

            const { emoji, color } = subredditInfo[subreddit];
            const embed = new EmbedBuilder()
                .setTitle(`${emoji} ${meme.title}`)
                .setURL(`https://reddit.com${meme.permalink}`)
                .setImage(meme.url)
                .setColor(color)
                .addFields([
                    { name: 'Subreddit', value: `r/${subreddit}`, inline: true },
                    { name: 'Author', value: `u/${meme.author}`, inline: true },
                    { name: 'Stats', value: `👍 ${meme.ups.toLocaleString()} | 💬 ${meme.num_comments.toLocaleString()}`, inline: true }
                ])
                .setFooter({ text: `Calls remaining: ${rateCheck.remaining} | Safe for work: ${meme.over_18 ? 'No' : 'Yes'}` })
                .setTimestamp();

            cache.set(cacheKey, embed);
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            console.error('Meme Error:', error);
            message.reply('Failed to fetch meme. Please try again later.');
        }
    },
};
