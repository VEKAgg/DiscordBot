const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');
const { formatTime } = require('../../utils/formatters');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'userinfo',
    description: 'Shows information about a user',
    category: 'utility',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    slashCommand: new SlashCommandBuilder()
        .setName('userinfo')
        .setDescription('Shows information about a user')
        .addUserOption(option =>
            option.setName('user')
                .setDescription('User to show information for')
                .setRequired(false)),

    async execute(interaction) {
        const targetUser = interaction.options.getUser('user') || interaction.user;
        const member = await interaction.guild.members.fetch(targetUser.id);

        const roles = member.roles.cache
            .filter(role => role.id !== interaction.guild.id)
            .sort((a, b) => b.position - a.position)
            .map(role => role.toString());

        const embed = new EmbedBuilder()
            .setTitle(`User Information - ${targetUser.tag}`)
            .setThumbnail(targetUser.displayAvatarURL({ dynamic: true }))
            .setColor('#2B2D31')
            .addFields([
                { name: 'User ID', value: targetUser.id, inline: true },
                { name: 'Nickname', value: member.nickname || 'None', inline: true },
                { name: 'Account Created', value: `<t:${Math.floor(targetUser.createdTimestamp / 1000)}:R>`, inline: true },
                { name: 'Joined Server', value: `<t:${Math.floor(member.joinedTimestamp / 1000)}:R>`, inline: true },
                { name: `Roles [${roles.length}]`, value: roles.join(', ') || 'None' }
            ])
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        await interaction.reply({ embeds: [embed] });
    }
};
