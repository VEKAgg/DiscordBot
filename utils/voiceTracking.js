const { logger } = require('./logger');
const VoiceActivity = require('../models/VoiceActivity');
const { trackUserActivity } = require('./tracking');

const voiceTracking = {
    activeConnections: new Map(), // Store active voice sessions

    async trackVoiceJoin(member, channel) {
        try {
            const now = new Date();
            this.activeConnections.set(member.id, {
                channelId: channel.id,
                guildId: channel.guild.id,
                startTime: now,
                isMuted: member.voice.mute,
                isDeafened: member.voice.deaf,
                isStreaming: member.voice.streaming,
                isVideo: member.voice.selfVideo
            });

            await trackUserActivity(member.user, channel.guild, 'voice_join', {
                channelId: channel.id,
                timestamp: now
            });
        } catch (error) {
            logger.error('Error tracking voice join:', error);
        }
    },

    async trackVoiceLeave(member) {
        try {
            const session = this.activeConnections.get(member.id);
            if (!session) return;

            const now = new Date();
            const duration = now - session.startTime;

            await VoiceActivity.create({
                userId: member.id,
                guildId: session.guildId,
                channelId: session.channelId,
                duration: duration,
                startTime: session.startTime,
                endTime: now,
                activityDetails: {
                    muted: session.isMuted,
                    deafened: session.isDeafened,
                    streaming: session.isStreaming,
                    video: session.isVideo
                }
            });

            this.activeConnections.delete(member.id);

            await trackUserActivity(member.user, member.guild, 'voice_leave', {
                duration,
                channelId: session.channelId,
                timestamp: now
            });
        } catch (error) {
            logger.error('Error tracking voice leave:', error);
        }
    },

    async getVoiceStats(guildId, timeframe = '7d') {
        try {
            const cutoff = new Date(Date.now() - this.getTimeframeMs(timeframe));
            
            const stats = await VoiceActivity.aggregate([
                {
                    $match: {
                        guildId: guildId,
                        startTime: { $gte: cutoff }
                    }
                },
                {
                    $group: {
                        _id: null,
                        totalSessions: { $sum: 1 },
                        totalDuration: { $sum: '$duration' },
                        avgSessionLength: { $avg: '$duration' },
                        uniqueUsers: { $addToSet: '$userId' },
                        streamingSessions: {
                            $sum: { $cond: [{ $eq: ['$activityDetails.streaming', true] }, 1, 0] }
                        },
                        videoSessions: {
                            $sum: { $cond: [{ $eq: ['$activityDetails.video', true] }, 1, 0] }
                        }
                    }
                }
            ]);

            return stats[0] || null;
        } catch (error) {
            logger.error('Error getting voice stats:', error);
            return null;
        }
    },

    getTimeframeMs(timeframe) {
        const times = {
            '1d': 24 * 60 * 60 * 1000,
            '7d': 7 * 24 * 60 * 60 * 1000,
            '30d': 30 * 24 * 60 * 60 * 1000
        };
        return times[timeframe] || times['7d'];
    }
};

module.exports = voiceTracking; 