const { EmbedBuilder } = require('discord.js');
const { User } = require('../database');

class LeaderboardManager {
    constructor(client) {
        this.client = client;
        this.leaderboardTypes = {
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
            }
        };
    }

    async getLeaderboardData(type, guildId, dateFilter = {}) {
        const query = { guildId };
        let sort = {};
        
        switch (type) {
            case 'gaming':
                return await User.aggregate([
                    { $match: query },
                    { $addFields: {
                        gameCount: { $size: { 
                            $filter: {
                                input: "$activity.richPresence",
                                as: "presence",
                                cond: { $eq: ["$$presence.type", "PLAYING"] }
                            }
                        }}
                    }},
                    { $sort: { gameCount: -1 } },
                    { $limit: 10 }
                ]);
            case 'voice':
                sort = { 'activity.voiceTime': -1 };
                break;
            case 'text':
                sort = { 'activity.messageCount': -1 };
                break;
            default:
                sort = { 'activity.totalScore': -1 };
        }

        return await User.find(query)
            .sort(sort)
            .limit(10)
            .lean();
    }

    createEmbed(data, type, timeRange, settings) {
        const embed = new EmbedBuilder()
            .setTitle(settings.title)
            .setColor(settings.color)
            .setDescription(settings.description)
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

    async execute(message, args) {
        const type = args[0]?.toLowerCase() || 'overall';
        const timeRange = args[1]?.toLowerCase() || 'all';
        
        if (!this.leaderboardTypes[type]) {
            return message.reply(`Invalid type! Available types: ${Object.keys(this.leaderboardTypes).join(', ')}`);
        }

        try {
            const data = await this.getLeaderboardData(type, message.guild.id);
            const embed = this.createEmbed(data, type, timeRange, this.leaderboardTypes[type]);
            message.channel.send({ embeds: [embed] });
        } catch (error) {
            console.error('Leaderboard Error:', error);
            message.reply('Failed to fetch leaderboard data.');
        }
    }
}

module.exports = LeaderboardManager;

function getDateFilter(timeRange) {
    const now = new Date();
    switch (timeRange) {
        case 'day':
            return { $gte: new Date(now.setDate(now.getDate() - 1)) };
        case 'week':
            return { $gte: new Date(now.setDate(now.getDate() - 7)) };
        case 'month':
            return { $gte: new Date(now.setMonth(now.getMonth() - 1)) };
        default:
            return {};
    }
}

function formatTime(minutes) {
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    return `${hours}h ${remainingMinutes}m`;
}

function formatStats(user, type) {
    if (!user || !user.activity) return 'No data';
    
    switch (type) {
        case 'gaming':
            const playingActivities = user.activity.richPresence?.filter(p => p.type === 'PLAYING') || [];
            const uniqueGames = [...new Set(playingActivities.map(p => p.name))].length;
            const totalTime = playingActivities.reduce((acc, curr) => acc + (curr.duration || 0), 0);
            return `${uniqueGames} games • ${formatTime(totalTime)}`;
        case 'voice':
            return formatTime(user.activity.voiceTime || 0);
        case 'text':
            return `${user.activity.messageCount || 0} messages`;
        default:
            return `Score: ${user.activity.totalScore || 0}`;
    }
}

function calculateOverallScore(user) {
    return Math.floor(
        user.activity.messageCount * 1 +
        user.activity.voiceTime * 2 +
        user.activity.richPresence.length * 5
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
