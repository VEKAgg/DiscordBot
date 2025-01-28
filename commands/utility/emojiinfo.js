const { SlashCommandBuilder, EmbedBuilder } = require('discord.js');
const { createEmbed } = require('../../utils/embedCreator');

module.exports = {
    name: 'emojiinfo',
    description: 'Show details about an emoji in the server',
    category: 'utility',
    slashCommand: new SlashCommandBuilder()
        .setName('emojiinfo')
        .setDescription('Show details about an emoji in the server')
        .addStringOption(option =>
            option.setName('emoji')
                .setDescription('The emoji to get information about (name or ID)')
                .setRequired(true)),

    async execute(interaction) {
        const isSlash = interaction.commandName !== undefined;
        const emojiInput = isSlash 
            ? interaction.options.getString('emoji')
            : interaction.args?.[0];

        if (!emojiInput) {
            const reply = { content: 'Please provide an emoji to fetch details for.', ephemeral: true };
            return isSlash ? interaction.reply(reply) : interaction.reply(reply.content);
        }

        try {
            const guild = isSlash ? interaction.guild : interaction.guild;
            const parsedEmoji = guild.emojis.cache.find(
                (e) => e.name === emojiInput || e.id === emojiInput
            );

            if (!parsedEmoji) {
                const reply = { content: 'Emoji not found in this server.', ephemeral: true };
                return isSlash ? interaction.reply(reply) : interaction.reply(reply.content);
            }

            const embed = new EmbedBuilder()
                .setTitle('🎨 Emoji Information')
                .setThumbnail(parsedEmoji.url)
                .setColor('#FF69B4')
                .addFields([
                    { name: 'Name', value: parsedEmoji.name, inline: true },
                    { name: 'ID', value: parsedEmoji.id, inline: true },
                    { name: 'Animated', value: parsedEmoji.animated ? 'Yes' : 'No', inline: true },
                    { name: 'Created', value: `<t:${Math.floor(parsedEmoji.createdTimestamp / 1000)}:R>`, inline: true },
                    { name: 'URL', value: `[Click Here](${parsedEmoji.url})`, inline: true }
                ])
                .setTimestamp();

            const reply = { embeds: [embed] };
            if (isSlash) {
                await interaction.reply(reply);
            } else {
                await interaction.channel.send(reply);
            }
        } catch (error) {
            logger.error('Emoji Info Error:', error);
            const reply = { 
                content: 'An error occurred while fetching emoji information.',
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
