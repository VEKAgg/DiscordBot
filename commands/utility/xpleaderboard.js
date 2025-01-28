const { EmbedBuilder, SlashCommandBuilder } = require('discord.js');
const { User } = require('../../database');

module.exports = {
    name: 'xpleaderboard',
    description: 'Shows the server XP leaderboard',
    usage: 'xpleaderboard',
    category: 'utility',
    slashCommand: new SlashCommandBuilder()
        .setName('xpleaderboard')
        .setDescription('Shows the server XP leaderboard'),

    async execute(interaction) {
        const isSlash = interaction.commandName !== undefined;
        const guildId = isSlash ? interaction.guildId : interaction.guild.id;
        const guildName = isSlash ? interaction.guild.name : interaction.guild.name;

        const users = await User.find({ guildId })
            .sort({ xp: -1 })
            .limit(10);

        const embed = new EmbedBuilder()
            .setTitle('🏆 XP Leaderboard')
            .setColor('#FFD700')
            .setDescription(
                users.map((user, index) => {
                    const level = Math.floor(Math.sqrt(user.xp / 100));
                    return `${index + 1}. <@${user.userId}> - Level ${level} (${user.xp} XP)`;
                }).join('\n')
            )
            .setFooter({ text: `${guildName}'s Top 10` });

        const reply = { embeds: [embed] };
        if (isSlash) {
            await interaction.reply(reply);
        } else {
            await interaction.channel.send(reply);
        }
    }
}; 