const { EmbedBuilder } = require('discord.js');
const { User } = require('../database');
const config = require('../config');
const SocialConnections = require('../utils/socialConnections');

module.exports = {
    name: 'guildMemberAdd',
    async execute(member) {
        try {
            // Get account age and check connections
            const accountAge = Math.floor((Date.now() - member.user.createdAt) / (1000 * 60 * 60 * 24));
            const isSuspicious = accountAge < 7;
            const connections = await member.user.fetchFlags();
            
            const socialConnections = await SocialConnections.getUserConnections(member);
            const isVerified = connections.size > 0 || Object.values(socialConnections).some(v => v);
            
            // Welcome embed with more info
            const welcomeEmbed = new EmbedBuilder()
                .setTitle(`Welcome to ${member.guild.name}! 👋`)
                .setDescription(`
                    Hey ${member}, welcome to our community! 🎉
                    You're member #${member.guild.memberCount}!
                    
                    📜 Check out <#${config.channels.rules}> to get started
                    🎮 Share your gaming activity in <#${config.channels.gaming}>
                    🗣️ Introduce yourself in <#${config.channels.introductions}>
                `)
                .setColor(isSuspicious ? '#FFA500' : '#2ECC71')
                .setThumbnail(member.user.displayAvatarURL())
                .addFields([
                    { name: 'Account Age', value: `${accountAge} days`, inline: true },
                    { name: 'Profile Status', value: connections.size ? '✅ Verified' : '⚠️ Limited', inline: true }
                ])
                .setImage(config.welcomeBanner)
                .setTimestamp();

            // Enhanced DM embed
            const dmEmbed = new EmbedBuilder()
                .setTitle(`Welcome to ${member.guild.name}!`)
                .setDescription('Here\'s your quick start guide:')
                .setColor('#3498DB')
                .addFields([
                    { 
                        name: '🔰 Getting Started',
                        value: `
                            1. Read the rules in <#${config.channels.rules}>
                            2. Get roles in <#${config.channels.roles}>
                            3. Introduce yourself in <#${config.channels.introductions}>
                        `
                    },
                    {
                        name: '🎮 Gaming Features',
                        value: `
                            • Your game activity will be tracked for roles
                            • Join others in <#${config.channels.lfg}>
                            • Share clips in <#${config.channels.highlights}>
                        `
                    },
                    {
                        name: '🤖 Bot Commands',
                        value: 'Type `/help` to see all available commands'
                    }
                ])
                .setFooter({ text: 'We hope you enjoy your stay!' });

            // Send welcome messages
            const welcomeChannel = member.guild.channels.cache.get(config.channels.welcome);
            if (welcomeChannel) {
                await welcomeChannel.send({ embeds: [welcomeEmbed] });
            }

            await member.send({ embeds: [dmEmbed] }).catch(() => {
                // If DM fails, send a message in welcome channel
                if (welcomeChannel) {
                    welcomeChannel.send(`Note: Couldn't DM ${member} - they might have DMs disabled.`);
                }
            });

            // Assign roles based on verification and connections
            await assignWelcomeRoles(member, isSuspicious, connections, socialConnections);

        } catch (error) {
            console.error('Welcome system error:', error);
        }
    }
};

async function assignWelcomeRoles(member, isSuspicious, connections, socialConnections) {
    const roles = {
        member: member.guild.roles.cache.get(config.roles.member),
        verified: member.guild.roles.cache.get(config.roles.verified),
        unverified: member.guild.roles.cache.get(config.roles.unverified),
        suspicious: member.guild.roles.cache.get(config.roles.suspicious)
    };

    try {
        // Remove any existing welcome-related roles
        await member.roles.remove(Object.values(roles).filter(Boolean));

        // Assign new roles
        const rolesToAdd = [];
        
        if (isSuspicious) {
            rolesToAdd.push(roles.suspicious);
        } else if (isVerified || Object.values(socialConnections).some(v => v)) {
            rolesToAdd.push(roles.verified);
            // Add any platform-specific roles
            await SocialConnections.processConnectionRoles(member, socialConnections);
        } else {
            rolesToAdd.push(roles.unverified);
        }

        rolesToAdd.push(roles.member);
        await member.roles.add(rolesToAdd.filter(Boolean));

    } catch (error) {
        console.error('Role assignment error:', error);
    }
}
