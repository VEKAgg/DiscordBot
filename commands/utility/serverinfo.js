const { SlashCommandBuilder, EmbedBuilder } = require('discord.js');
const { formatTime } = require('../../utils/formatters');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'serverinfo',
    description: 'Shows information about the server',
    category: 'utility',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    slashCommand: new SlashCommandBuilder()
        .setName('serverinfo')
        .setDescription('Shows detailed information about the server'),

    async execute(interaction) {
        const isSlash = interaction.commandName !== undefined;
        const guild = isSlash ? interaction.guild : interaction.guild;
        
        try {
            const owner = await guild.fetchOwner();
            const channels = guild.channels.cache;
            const roles = guild.roles.cache;

            const embed = new EmbedBuilder()
                .setTitle(`${guild.name} Server Information`)
                .setThumbnail(guild.iconURL({ dynamic: true }))
                .setColor('#0099ff')
                .addFields([
                    { name: '👑 Owner', value: `${owner.user.tag}`, inline: true },
                    { name: '📅 Created', value: `<t:${Math.floor(guild.createdTimestamp / 1000)}:R>`, inline: true },
                    { name: '🌍 Region', value: guild.preferredLocale, inline: true },
                    { name: '👥 Members', value: `
                        Total: ${guild.memberCount}
                        Users: ${guild.members.cache.filter(m => !m.user.bot).size}
                        Bots: ${guild.members.cache.filter(m => m.user.bot).size}
                    `, inline: true },
                    { name: '📊 Channels', value: `
                        Total: ${channels.size}
                        Text: ${channels.filter(c => c.type === 0).size}
                        Voice: ${channels.filter(c => c.type === 2).size}
                        Categories: ${channels.filter(c => c.type === 4).size}
                    `, inline: true },
                    { name: '🏷️ Roles', value: `${roles.size} roles`, inline: true },
                    { name: '🔰 Boost Status', value: `
                        Level: ${guild.premiumTier}
                        Boosts: ${guild.premiumSubscriptionCount || 0}
                    `, inline: true }
                ])
                .setFooter({ text: `Server ID: ${guild.id} • Contributed by ${this.contributor} • ${getRandomFooter()}` })
                .setTimestamp();

            if (guild.banner) {
                embed.setImage(guild.bannerURL({ dynamic: true }));
            }

            const reply = { embeds: [embed] };
            if (isSlash) {
                await interaction.reply(reply);
            } else {
                await interaction.channel.send(reply);
            }
        } catch (error) {
            logger.error('Server Info Error:', error);
            const reply = { 
                content: 'Failed to fetch server information.',
                ephemeral: true 
            };
            if (isSlash) {
                await interaction.reply(reply);
            } else {
                await interaction.reply(reply.content);
            }
        }
    }
};
