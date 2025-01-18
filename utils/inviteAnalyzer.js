const { User } = require('../database');
const { logger } = require('./logger');

class InviteAnalyzer {
    static async checkForAbuse(member, inviter) {
        try {
            const suspiciousPatterns = await this.detectSuspiciousPatterns(member, inviter);
            if (suspiciousPatterns.length > 0) {
                await this.reportSuspiciousActivity(member.guild, inviter, suspiciousPatterns);
                return true;
            }
            return false;
        } catch (error) {
            logger.error('Error in invite abuse detection:', error);
            return false;
        }
    }

    static async detectSuspiciousPatterns(member, inviter) {
        const patterns = [];
        const timeWindow = 24 * 60 * 60 * 1000; // 24 hours

        // Get inviter's recent invites
        const inviterData = await User.findOne({ 
            userId: inviter.id,
            guildId: member.guild.id
        });

        if (!inviterData?.invites?.history) return patterns;

        const recentInvites = inviterData.invites.history.filter(
            invite => Date.now() - new Date(invite.timestamp) < timeWindow
        );

        // Check for suspicious patterns
        if (recentInvites.length > 10) {
            patterns.push('High invite frequency');
        }

        if (member.user.createdTimestamp > Date.now() - 7 * 24 * 60 * 60 * 1000) {
            patterns.push('New account invited');
        }

        const uniqueIPs = new Set(recentInvites.map(i => i.ip));
        if (uniqueIPs.size === 1 && recentInvites.length > 3) {
            patterns.push('Multiple accounts from same IP');
        }

        return patterns;
    }

    static async reportSuspiciousActivity(guild, inviter, patterns) {
        const logChannel = guild.channels.cache.find(ch => ch.name === 'mod-logs');
        if (!logChannel) return;

        const embed = new EmbedBuilder()
            .setTitle('⚠️ Suspicious Invite Activity Detected')
            .setDescription(`Suspicious activity detected from ${inviter.tag}`)
            .addFields([
                { name: 'Inviter', value: `<@${inviter.id}>`, inline: true },
                { name: 'Inviter ID', value: inviter.id, inline: true },
                { name: 'Detected Patterns', value: patterns.join('\n') }
            ])
            .setColor('#ff0000')
            .setTimestamp();

        await logChannel.send({ embeds: [embed] });
    }
}

module.exports = InviteAnalyzer; 