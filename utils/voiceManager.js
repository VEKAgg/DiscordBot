const { joinVoiceChannel } = require('@discordjs/voice');
const { logger } = require('./logger');

class VoiceManager {
    static async ensureVoiceConnection(client, guildId, channelId) {
        try {
            const guild = client.guilds.cache.get(guildId);
            if (!guild) throw new Error('Guild not found');

            const channel = guild.channels.cache.get(channelId);
            if (!channel || channel.type !== 'GUILD_VOICE') throw new Error('Voice channel not found');

            joinVoiceChannel({
                channelId: channel.id,
                guildId: guild.id,
                adapterCreator: guild.voiceAdapterCreator,
                selfDeaf: true
            });

            return true;
        } catch (error) {
            console.error('Failed to join voice channel:', error);
            return false;
        }
    }

    static async reconnectVoice(client, guildId, channelId) {
        try {
            const success = await this.ensureVoiceConnection(client, guildId, channelId);
            if (!success) {
                setTimeout(() => this.reconnectVoice(client, guildId, channelId), 300000); // Retry every 5 minutes
            }
        } catch (error) {
            logger.error('Error in voice reconnection:', error);
        }
    }
}

module.exports = VoiceManager;
