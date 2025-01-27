const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { logger } = require('../../utils/logger');

module.exports = {
    name: 'roles',
    description: 'Manage server roles',
    category: 'admin',
    slashCommand: new SlashCommandBuilder()
        .setName('roles')
        .setDescription('Manage server roles')
        .setDefaultMemberPermissions(PermissionFlagsBits.ManageRoles)
        .addSubcommand(subcommand =>
            subcommand
                .setName('add')
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
            subcommand
                .setName('remove')
                .setDescription('Remove a role from a user')
                .addUserOption(option =>
                    option.setName('user')
                        .setDescription('User to remove role from')
                        .setRequired(true))
                .addRoleOption(option =>
                    option.setName('role')
                        .setDescription('Role to remove')
                        .setRequired(true)))
        .addSubcommand(subcommand =>
            subcommand
                .setName('info')
                .setDescription('Get information about a role')
                .addRoleOption(option =>
                    option.setName('role')
                        .setDescription('Role to get info about')
                        .setRequired(true))),

    async execute(interaction) {
        if (!interaction.member.permissions.has(PermissionFlagsBits.ManageRoles)) {
            return interaction.reply({
                content: 'You need Manage Roles permission to use this command.',
                ephemeral: true
            });
        }

        const subcommand = interaction.options.getSubcommand();

        try {
            switch (subcommand) {
                case 'add': {
                    const user = interaction.options.getUser('user');
                    const role = interaction.options.getRole('role');
                    const member = await interaction.guild.members.fetch(user.id);

                    if (member.roles.cache.has(role.id)) {
                        return interaction.reply({
                            content: `${user} already has the ${role} role.`,
                            ephemeral: true
                        });
                    }

                    await member.roles.add(role);
                    return interaction.reply({
                        content: `Added ${role} role to ${user}.`,
                        ephemeral: true
                    });
                }

                case 'remove': {
                    const user = interaction.options.getUser('user');
                    const role = interaction.options.getRole('role');
                    const member = await interaction.guild.members.fetch(user.id);

                    if (!member.roles.cache.has(role.id)) {
                        return interaction.reply({
                            content: `${user} doesn't have the ${role} role.`,
                            ephemeral: true
                        });
                    }

                    await member.roles.remove(role);
                    return interaction.reply({
                        content: `Removed ${role} role from ${user}.`,
                        ephemeral: true
                    });
                }

                case 'info': {
                    const role = interaction.options.getRole('role');
                    const embed = new EmbedBuilder()
                        .setTitle('Role Information')
                        .setColor(role.color)
                        .addFields([
                            { name: 'Name', value: role.name, inline: true },
                            { name: 'ID', value: role.id, inline: true },
                            { name: 'Color', value: role.hexColor, inline: true },
                            { name: 'Position', value: role.position.toString(), inline: true },
                            { name: 'Mentionable', value: role.mentionable ? 'Yes' : 'No', inline: true },
                            { name: 'Hoisted', value: role.hoist ? 'Yes' : 'No', inline: true },
                            { name: 'Created', value: `<t:${Math.floor(role.createdTimestamp / 1000)}:R>`, inline: true },
                            { name: 'Members', value: role.members.size.toString(), inline: true }
                        ]);

                    return interaction.reply({ embeds: [embed] });
                }
            }
        } catch (error) {
            logger.error('Roles command error:', error);
            return interaction.reply({
                content: 'An error occurred while managing roles.',
                ephemeral: true
            });
        }
    }
}; 