const { SlashCommandBuilder, EmbedBuilder } = require('discord.js');
const { User } = require('../../database');
const { formatTime } = require('../../utils/formatters');

module.exports = {
    name: 'userinfo',
    description: 'Shows detailed information about a user',
    category: 'utility',
    slashCommand: new SlashCommandBuilder()
        .setName('userinfo')
        .setDescription('Shows detailed information about a user')
        .addUserOption(option =>
            option.setName('user')
                .setDescription('User to get information about')
                .setRequired(false)),

    async execute(interaction) {
        const isSlash = interaction.commandName !== undefined;
        const target = isSlash 
            ? interaction.options.getUser('user')?.member || interaction.member
            : interaction.mentions.members.first() || interaction.member;

        try {
            const roles = target.roles.cache
                .sort((a, b) => b.position - a.position)
                .map(role => role)
                .slice(0, 10);

            const userData = await User.findOne({ 
                userId: target.id,
                guildId: isSlash ? interaction.guildId : interaction.guild.id 
            });

            const embed = new EmbedBuilder()
                .setTitle(`${target.user.tag}'s Information`)
                .setThumbnail(target.user.displayAvatarURL({ dynamic: true }))
                .setColor(target.displayHexColor || '#0099ff')
                .addFields([
                    { 
                        name: '👤 Account Info',
                        value: `**ID:** ${target.id}\n**Created:** <t:${Math.floor(target.user.createdTimestamp / 1000)}:R>\n**Joined:** <t:${Math.floor(target.joinedTimestamp / 1000)}:R>`,
                        inline: false 
                    },
                    { 
                        name: '🎭 Server Profile',
                        value: `**Nickname:** ${target.nickname || 'None'}\n**Top Role:** ${target.roles.highest}\n**Color:** ${target.displayHexColor}`,
                        inline: false 
                    },
                    {
                        name: `📋 Roles [${roles.length}]`,
                        value: roles.join(', ') || 'No roles',
                        inline: false
                    }
                ]);

            if (userData) {
                embed.addFields([
                    {
                        name: '📊 Activity Stats',
                        value: `**Level:** ${Math.floor(Math.sqrt(userData.xp / 100))}\n**XP:** ${userData.xp}\n**Messages:** ${userData.activity?.messageCount || 0}\n**Voice Time:** ${formatTime(userData.activity?.voiceTime || 0)}`,
                        inline: false
                    }
                ]);
            }

            if (target.user.banner) {
                embed.setImage(target.user.bannerURL({ dynamic: true }));
            }

            const reply = { embeds: [embed] };
            if (isSlash) {
                await interaction.reply(reply);
            } else {
                await interaction.channel.send(reply);
            }
        } catch (error) {
            logger.error('User Info Error:', error);
            const reply = { 
                content: 'Failed to fetch user information.',
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
