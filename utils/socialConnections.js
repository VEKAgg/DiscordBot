const { EmbedBuilder } = require('discord.js');
const axios = require('axios');
const { User } = require('../database');
const { logger } = require('./logger');
const ConnectionAnalytics = require('./connectionAnalytics');

class SocialConnections {
    static async getUserConnections(member) {
        try {
            const user = await member.user.fetch(true); // Force fetch to get all data
            const connections = await user.fetchFlags();
            
            // Enhanced verified connections check
            const verifiedAccounts = {
                github: {
                    verified: connections.has('VERIFIED_DEVELOPER'),
                    data: await this.getGithubData(member),
                },
                twitch: {
                    verified: connections.has('PARTNERED_SERVER_OWNER'),
                    data: await this.getTwitchData(member),
                },
                youtube: {
                    verified: connections.has('DISCORD_PARTNER'),
                    data: await this.getYoutubeData(member),
                },
                spotify: {
                    verified: connections.has('PREMIUM_EARLY_SUPPORTER'),
                    data: await this.getSpotifyData(member),
                },
                reddit: {
                    verified: connections.has('ACTIVE_DEVELOPER'),
                    data: await this.getRedditData(member),
                },
                steam: {
                    verified: connections.has('HOUSE_BRILLIANCE'),
                    data: await this.getSteamData(member),
                }
            };

            // Process roles and send alerts
            await this.processVerification(member, verifiedAccounts);
            await ConnectionAnalytics.trackConnection(member, verifiedAccounts);
            return verifiedAccounts;

        } catch (error) {
            logger.error('Social connections error:', error);
            return null;
        }
    }

    static async processVerification(member, connections) {
        const significantPresence = this.analyzePresence(connections);
        
        if (significantPresence.isSignificant) {
            await StaffAlerts.send(member.guild, {
                type: 'verification',
                priority: significantPresence.priority,
                content: 'Notable social presence detected',
                data: {
                    user: `<@${member.id}>`,
                    platforms: significantPresence.platforms.join(', '),
                    metrics: significantPresence.metrics
                }
            });
        }
    }

    static analyzePresence(connections) {
        const metrics = {};
        const platforms = [];
        let score = 0;

        // Platform-specific scoring
        if (connections.github.verified && connections.github.data) {
            const { followers, repos } = connections.github.data;
            score += followers * 0.5 + repos * 0.3;
            platforms.push('GitHub');
            metrics.github = `${followers} followers, ${repos} repos`;
        }

        // Add similar checks for other platforms...

        return {
            isSignificant: score > 100,
            priority: score > 1000 ? 'high' : 'medium',
            platforms,
            metrics
        };
    }

    // Platform-specific data fetchers
    static async getGithubData(member) {
        // Implementation using GitHub API
    }

    static async getTwitchData(member) {
        // Implementation using Twitch API
    }

    // ... other platform methods
}

module.exports = SocialConnections; 