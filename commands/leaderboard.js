const { EmbedBuilder } = require('discord.js');
const { User } = require('../database');

module.exports = {
    name: 'leaderboard',
    description: 'View various server leaderboards',
    async execute(message, args) {
        const type = args[0]?.toLowerCase() || 'overall';
        const timeRange = args[1]?.toLowerCase() || 'all';

        const leaderboardTypes = {
            overall: { 
                title: '🏆 Overall Activity', 
                color: '#FFD700',
                description: 'Combined score from all activities'
            },
            gaming: { 
                title: '🎮 Gaming Time', 
                color: '#7289DA',
                description: 'Time spent playing games'
            },
            voice: { 
                title: '🎤 Voice Activity', 
                color: '#2ECC71',
                description: 'Time spent in voice channels'
            },
            text: { 
                title: '💬 Chat Activity', 
                color: '#3498DB',
                description: 'Messages sent in text channels'
            },
            daily: { 
                title: '📅 Daily Streak', 
                color: '#E74C3C',
                description: 'Consecutive days active'
            },
            reactions: { 
                title: '😄 Reaction Master', 
                color: '#F1C40F',
                description: 'Reactions given and received'
            },
            helpful: { 
                title: '🤝 Most Helpful', 
                color: '#9B59B6',
                description: 'Based on reactions to answers/help'
            },
            nightowl: { 
                title: '🦉 Night Owl', 
                color: '#34495E',
                description: 'Activity between 10 PM and 6 AM'
            },
            weekend: { 
                title: '🎉 Weekend Warrior', 
                color: '#E67E22',
                description: 'Activity during weekends'
            },
            social: { 
                title: '🫂 Social Butterfly', 
                color: '#FF69B4',
                description: 'Interactions with other members'
            }
        };

        if (!leaderboardTypes[type]) {
            const types = Object.keys(leaderboardTypes)
                .map(t => `\`${t}\``)
                .join(', ');
            return message.reply(`Invalid leaderboard type! Available types: ${types}`);
        }

        try {
            const dateFilter = getDateFilter(timeRange);
            const users = await getLeaderboardData(type, message.guild.id, dateFilter);
            const embed = createLeaderboardEmbed(users, type, timeRange, leaderboardTypes[type]);
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            console.error('Leaderboard Error:', error);
            message.reply('Failed to fetch leaderboard data.');
        }
    }
};

function getDateFilter(timeRange) {
    const now = new Date();
    switch (timeRange) {
        case 'week':
            return new Date(now.setDate(now.getDate() - 7));
        case 'month':
            return new Date(now.setMonth(now.getMonth() - 1));
        default:
            return null;
    }
}

async function getLeaderboardData(type, guildId, dateFilter) {
    let query = { guildId };
    if (dateFilter) {
        query['activity.lastSeen'] = { $gte: dateFilter };
    }

    let sortCriteria = {};
    switch (type) {
        case 'gaming':
            sortCriteria = { 'activity.richPresence': -1 };
            break;
        case 'voice':
            sortCriteria = { 'activity.voiceTime': -1 };
            break;
        case 'text':
            sortCriteria = { 'activity.messageCount': -1 };
            break;
        case 'games':
            return User.aggregate([
                { $match: query },
                { $unwind: '$activity.richPresence' },
                { $group: {
                    _id: '$activity.richPresence.game',
                    totalTime: { $sum: '$activity.richPresence.duration' },
                    playerCount: { $addToSet: '$userId' }
                }},
                { $sort: { totalTime: -1 }},
                { $limit: 10 }
            ]);
        default:
            // Overall score calculation
            sortCriteria = {
                $expr: {
                    $add: [
                        { $multiply: ['$activity.voiceTime', 0.5] },
                        { $multiply: ['$activity.messageCount', 1] },
                        { $size: '$activity.richPresence' }
                    ]
                }
            };
    }

    return User.find(query).sort(sortCriteria).limit(10);
}

function createLeaderboardEmbed(data, type, timeRange, { title, color, description }) {
    const embed = new EmbedBuilder()
        .setTitle(title)
        .setColor(color)
        .setDescription(description)
        .setTimestamp();

    if (type === 'games') {
        const description = data.map((game, index) => 
            `${index + 1}. **${game._id}**\n` +
            `⏰ ${formatTime(game.totalTime)}\n` +
            `👥 ${game.playerCount.length} players\n`
        ).join('\n');
        embed.setDescription(description);
    } else {
        const description = data.map((user, index) => 
            `${index + 1}. <@${user.userId}> - ${formatStats(user, type)}`
        ).join('\n');
        embed.setDescription(description || 'No data available');
    }

    embed.setFooter({ 
        text: `Timeframe: ${timeRange.charAt(0).toUpperCase() + timeRange.slice(1)}` 
    });

    return embed;
}

function formatTime(minutes) {
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    return `${hours}h ${remainingMinutes}m`;
}

function formatStats(user, type) {
    switch (type) {
        case 'gaming':
            return `${user.activity.richPresence.length} games played`;
        case 'voice':
            return formatTime(user.activity.voiceTime);
        case 'text':
            return `${user.activity.messageCount} messages`;
        default:
            return `Score: ${calculateOverallScore(user)}`;
    }
}

function calculateOverallScore(user) {
    return Math.floor(
        (user.activity.voiceTime * 0.5) +
        (user.activity.messageCount * 1) +
        (user.activity.richPresence.length * 2)
    );
}

function calculateScore(user, type, timeRange) {
    switch (type) {
        case 'daily':
            return user.activity.dailyStreak || 0;
        case 'reactions':
            return (user.activity.reactionsGiven || 0) + (user.activity.reactionsReceived || 0);
        case 'helpful':
            return calculateHelpfulScore(user);
        case 'nightowl':
            return calculateNightOwlScore(user, timeRange);
        case 'weekend':
            return calculateWeekendScore(user, timeRange);
        case 'social':
            return calculateSocialScore(user);
        default:
            return calculateOverallScore(user);
    }
}

function calculateHelpfulScore(user) {
    const helpReactions = user.activity.reactionsReceived?.filter(r => 
        ['✅', '👍', '⭐', '🙏'].includes(r.emoji)
    ).length || 0;
    const helpMessages = user.activity.messageCount || 0;
    return (helpReactions * 2) + (helpMessages * 0.5);
}

function calculateNightOwlScore(user, timeRange) {
    return user.activity.richPresence
        .filter(presence => {
            const hour = new Date(presence.timestamp).getHours();
            return hour >= 22 || hour < 6;
        })
        .length;
}

function calculateWeekendScore(user, timeRange) {
    return user.activity.richPresence
        .filter(presence => {
            const day = new Date(presence.timestamp).getDay();
            return day === 0 || day === 6;
        })
        .length;
}

function calculateSocialScore(user) {
    const voiceScore = user.activity.voiceTime * 2;
    const messageScore = user.activity.messageCount;
    const reactionScore = (user.activity.reactionsGiven || 0) * 0.5;
    const mentionScore = (user.activity.mentionsReceived || 0) * 1.5;
    return voiceScore + messageScore + reactionScore + mentionScore;
}
