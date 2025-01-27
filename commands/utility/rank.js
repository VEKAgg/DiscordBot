const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');
const { User } = require('../../database');
const { XPManager } = require('../../utils/xpManager');

module.exports = {
    name: 'rank',
    description: 'Shows your current rank, level, and XP progress',
    usage: 'rank [@user]',
    category: 'utility',
    slashCommand: new SlashCommandBuilder()
        .setName('rank')
        .setDescription('Shows your current rank and level')
        .addUserOption(option =>
            option.setName('user')
                .setDescription('User to check rank for')
                .setRequired(false)),

    async execute(interaction) {
        const isSlash = interaction.commandName !== undefined;
        const target = isSlash 
            ? interaction.options.getUser('user') || interaction.user
            : interaction.mentions.users.first() || interaction.author;

        const userData = await User.findOne({ 
            userId: target.id,
            guildId: isSlash ? interaction.guildId : interaction.guild.id
        });

        if (!userData) {
            const reply = { content: 'No XP data found for this user.', ephemeral: true };
            return isSlash ? interaction.reply(reply) : interaction.reply(reply.content);
        }

        const level = XPManager.calculateLevel(userData.xp);
        const nextLevelXP = XPManager.calculateNextLevelXP(level);
        const progress = (userData.xp / nextLevelXP) * 100;
        const progressBar = XPManager.createProgressBar(progress);

        const embed = new EmbedBuilder()
            .setTitle(`${target.username}'s Rank`)
            .setThumbnail(target.displayAvatarURL())
            .setColor('#0099ff')
            .addFields([
                { name: 'Level', value: level.toString(), inline: true },
                { name: 'XP', value: `${userData.xp}/${nextLevelXP}`, inline: true },
                { name: 'Progress', value: progressBar }
            ])
            .setFooter({ text: `Rank stats for ${target.tag}` });

        const reply = { embeds: [embed] };
        if (isSlash) {
            await interaction.reply(reply);
        } else {
            await interaction.channel.send(reply);
        }
    }
}; 