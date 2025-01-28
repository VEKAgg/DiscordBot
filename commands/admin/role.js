const { EmbedBuilder, SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'role',
    description: 'Manage user roles',
    category: 'admin',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    permissions: [PermissionFlagsBits.ManageRoles],
    slashCommand: new SlashCommandBuilder()
        .setName('role')
        .setDescription('Manage user roles')
        .setDefaultMemberPermissions(PermissionFlagsBits.ManageRoles)
        .addSubcommand(subcommand =>
            subcommand.setName('add')
                .setDescription('Add a role to a user')
                .addUserOption(option =>
                    option.setName('user')
                        .setDescription('User to add role to')
                        .setRequired(true))
                .addRoleOption(option =>
                    option.setName('role')
                        .setDescription('Role to add')
                        .setRequired(true)))
        .addSubcommand(subcommand =>
            subcommand.setName('remove')
                .setDescription('Remove a role from a user')
                .addUserOption(option =>
                    option.setName('user')
                        .setDescription('User to remove role from')
                        .setRequired(true))
                .addRoleOption(option =>
                    option.setName('role')
                        .setDescription('Role to remove')
                        .setRequired(true))),

    async execute(interaction) {
        const subcommand = interaction.options.getSubcommand();
        const targetUser = interaction.options.getUser('user');
        const role = interaction.options.getRole('role');
        const member = await interaction.guild.members.fetch(targetUser.id);

        if (role.position >= interaction.member.roles.highest.position) {
            return interaction.reply({
                content: 'You cannot manage roles higher than or equal to your highest role.',
                ephemeral: true
            });
        }

        const embed = new EmbedBuilder()
            .setColor('#2B2D31')
            .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

        try {
            if (subcommand === 'add') {
                await member.roles.add(role);
                embed
                    .setTitle('Role Added')
                    .addFields([
                        { name: 'User', value: targetUser.tag, inline: true },
                        { name: 'Role', value: role.name, inline: true },
                        { name: 'Moderator', value: interaction.user.tag, inline: true }
                    ]);
            } else {
                await member.roles.remove(role);
                embed
                    .setTitle('Role Removed')
                    .addFields([
                        { name: 'User', value: targetUser.tag, inline: true },
                        { name: 'Role', value: role.name, inline: true },
                        { name: 'Moderator', value: interaction.user.tag, inline: true }
                    ]);
            }

            await interaction.reply({ embeds: [embed] });
        } catch (error) {
            return interaction.reply({
                content: 'There was an error trying to manage roles.',
                ephemeral: true
            });
        }
    }
}; 