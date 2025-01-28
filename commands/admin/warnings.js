const { EmbedBuilder, SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { User } = require('../../database');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'warnings',
    description: 'View or manage user warnings',
    category: 'admin',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    permissions: [PermissionFlagsBits.ModerateMembers],
    slashCommand: new SlashCommandBuilder()
        .setName('warnings')
        .setDescription('View or manage user warnings')
        .setDefaultMemberPermissions(PermissionFlagsBits.ModerateMembers)
        .addSubcommand(subcommand =>
            subcommand.setName('view')
                .setDescription('View warnings for a user')
                .addUserOption(option =>
                    option.setName('user')
                        .setDescription('User to check warnings for')
                        .setRequired(true)))
        .addSubcommand(subcommand =>
            subcommand.setName('add')
                .setDescription('Add a warning to a user')
                .addUserOption(option =>
                    option.setName('user')
                        .setDescription('User to warn')
                        .setRequired(true))
                .addStringOption(option =>
                    option.setName('reason')
                        .setDescription('Reason for the warning')
                        .setRequired(true)))
        .addSubcommand(subcommand =>
            subcommand.setName('remove')
                .setDescription('Remove a warning from a user')
                .addUserOption(option =>
                    option.setName('user')
                        .setDescription('User to remove warning from')
                        .setRequired(true))
                .addIntegerOption(option =>
                    option.setName('warning')
                        .setDescription('Warning number to remove')
                        .setRequired(true))),

    async execute(interaction) {
        const subcommand = interaction.options.getSubcommand();
        const targetUser = interaction.options.getUser('user');
        let userData = await User.findOne({ userId: targetUser.id, guildId: interaction.guildId });

        if (!userData) {
            userData = await User.create({
                userId: targetUser.id,
                guildId: interaction.guildId,
                warnings: []
            });
        }

        switch (subcommand) {
            case 'view': {
                const embed = new EmbedBuilder()
                    .setTitle(`Warnings for ${targetUser.tag}`)
                    .setColor('#2B2D31')
                    .setDescription(
                        userData.warnings.length > 0 ?
                            userData.warnings.map((warning, index) =>
                                `${index + 1}. ${warning.reason} (by ${warning.moderator})`
                            ).join('\n') :
                            'No warnings found'
                    )
                    .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

                await interaction.reply({ embeds: [embed] });
                break;
            }
            case 'add': {
                const reason = interaction.options.getString('reason');
                userData.warnings.push({
                    reason,
                    moderator: interaction.user.tag,
                    timestamp: new Date()
                });
                await userData.save();

                const embed = new EmbedBuilder()
                    .setTitle('Warning Added')
                    .setColor('#2B2D31')
                    .addFields([
                        { name: 'User', value: targetUser.tag, inline: true },
                        { name: 'Moderator', value: interaction.user.tag, inline: true },
                        { name: 'Reason', value: reason }
                    ])
                    .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

                await interaction.reply({ embeds: [embed] });
                break;
            }
            case 'remove': {
                const warningNumber = interaction.options.getInteger('warning') - 1;

                if (warningNumber < 0 || warningNumber >= userData.warnings.length) {
                    return interaction.reply({
                        content: 'Invalid warning number.',
                        ephemeral: true
                    });
                }

                userData.warnings.splice(warningNumber, 1);
                await userData.save();

                const embed = new EmbedBuilder()
                    .setTitle('Warning Removed')
                    .setColor('#2B2D31')
                    .addFields([
                        { name: 'User', value: targetUser.tag, inline: true },
                        { name: 'Moderator', value: interaction.user.tag, inline: true },
                        { name: 'Warning Number', value: (warningNumber + 1).toString() }
                    ])
                    .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

                await interaction.reply({ embeds: [embed] });
                break;
            }
        }
    }
}; 