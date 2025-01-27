const { SlashCommandBuilder, EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'avatar',
    description: 'Get user avatar',
    category: 'utility',
    contributor: 'Sleepless',
    slashCommand: new SlashCommandBuilder()
        .setName('avatar')
        .setDescription('Get user avatar')
        .addUserOption(option =>
            option.setName('user')
                .setDescription('User to get avatar from')
                .setRequired(false)),

    async execute(interaction) {
        const isSlash = interaction.commandName !== undefined;
        const target = isSlash
            ? interaction.options.getUser('user') || interaction.user
            : interaction.mentions.users.first() || interaction.author;

        try {
            const embed = new EmbedBuilder()
                .setTitle(`${target.username}'s Avatar`)
                .setDescription(`[Click to download](${target.displayAvatarURL({ size: 4096, dynamic: true })})`)
                .setImage(target.displayAvatarURL({ size: 4096, dynamic: true }))
                .setColor('#0099ff')
                .setAuthor({
                    name: isSlash ? interaction.user.tag : interaction.author.tag,
                    iconURL: isSlash ? interaction.user.displayAvatarURL({ dynamic: true }) 
                        : interaction.author.displayAvatarURL({ dynamic: true })
                })
                .setFooter({
                    text: `Contributor: ${module.exports.contributor} • VEKA`,
                    iconURL: interaction.client.user.displayAvatarURL()
                })
                .setTimestamp();

            const reply = { embeds: [embed] };
            if (isSlash) {
                await interaction.reply(reply);
            } else {
                await interaction.channel.send(reply);
            }
        } catch (error) {
            logger.error('Avatar Command Error:', error);
            const reply = { 
                content: 'Failed to fetch avatar.',
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