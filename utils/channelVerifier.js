const { EmbedBuilder } = require('discord.js');
const NodeCache = require('node-cache');
const { logger } = require('./logger');
const { ChannelType } = require('discord.js');

class ChannelVerifier {
    constructor(client) {
        this.client = client;
        this.pauseCache = new NodeCache({ stdTTL: 2592000 }); // 30 days
        this.channelTypes = {
            'dashboard': {
                keywords: ['dashboard', 'stats', 'leaderboard', 'ranking', 'bot-stats', '📊', '📈'],
                purpose: 'Server statistics and leaderboards'
            },
            'logs': {
                keywords: ['log', 'audit', 'server-log', 'mod-log', 'logs', '📝'],
                purpose: 'Server activity logging'
            },
            'staff': {
                keywords: ['staff', 'admin', 'mod', 'moderator', 'team', '👮', '🛡️'],
                purpose: 'Staff notifications and controls'
            }
        };

        // Setup message collector for pause responses
        client.on('messageCreate', this.handlePauseResponse.bind(this));
    }

    async handlePauseResponse(message) {
        if (message.content.toLowerCase() === 'pause notifications') {
            this.pauseCache.set(`pause_${message.guild.id}`, true);
            message.reply('✅ Channel setup notifications paused for 30 days.');
            logger.info(`Channel notifications paused for guild ${message.guild.id}`);
        }
    }

    findChannelByType(guild, type) {
        const channelConfig = this.channelTypes[type];
        if (!channelConfig) return null;

        return guild.channels.cache.find(ch => 
            ch.type === ChannelType.GuildText && 
            channelConfig.keywords.some(keyword => 
                ch.name.toLowerCase().replace(/[^a-z0-9]/g, '').includes(
                    keyword.toLowerCase().replace(/[^a-z0-9]/g, '')
                )
            )
        );
    }

    async verifyChannels(guild) {
        if (this.pauseCache.get(`pause_${guild.id}`)) return;

        const missingChannels = {};
        for (const [type, config] of Object.entries(this.channelTypes)) {
            if (!this.findChannelByType(guild, type)) {
                missingChannels[type] = config.purpose;
            }
        }

        if (Object.keys(missingChannels).length === 0) return;

        const staffChannel = this.findChannelByType(guild, 'staff');
        const owner = await guild.fetchOwner();

        const embed = new EmbedBuilder()
            .setTitle('⚠️ Channel Setup Required')
            .setDescription('The following channels are required for full bot functionality:')
            .addFields(
                Object.entries(missingChannels).map(([type, purpose]) => ({
                    name: `${this.channelTypes[type].keywords[0]}`,
                    value: `Purpose: ${purpose}\nSuggested names: ${this.channelTypes[type].keywords.slice(0, 3).join(', ')}`,
                    inline: false
                }))
            )
            .setColor('#FF9900')
            .setFooter({ 
                text: 'Use !channel create <type> to set up these channels, or !pause to stop notifications' 
            });

        if (staffChannel) {
            await staffChannel.send({ embeds: [embed] });
        } else {
            await owner.send({ 
                content: '⚠️ Your server needs some channels set up for the bot to work properly:',
                embeds: [embed] 
            }).catch(() => logger.warn(`Could not DM owner of ${guild.name}`));
        }
    }
}

module.exports = ChannelVerifier; 