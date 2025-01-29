const { EmbedBuilder, SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const fs = require('fs');
const path = require('path');
const { getRandomFooter } = require('../../utils/footerRotator');

module.exports = {
    name: 'files',
    description: 'Shows bot file structure',
    category: 'utility',
    contributor: 'TwistedVorteK (@https://github.com/twistedvortek/)',
    permissions: [PermissionFlagsBits.Administrator],
    slashCommand: new SlashCommandBuilder()
        .setName('files')
        .setDescription('Shows bot file structure')
        .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),

    async execute(interaction) {
        try {
            const rootDir = path.join(__dirname, '../../');
            let fileStructure = this.getDirectoryStructure(rootDir);

            const embed = new EmbedBuilder()
                .setTitle('Bot File Structure')
                .setColor('#2B2D31')
                .setDescription('```\n' + fileStructure + '\n```')
                .setFooter({ text: `Contributed by ${this.contributor} • ${getRandomFooter()}` });

            await interaction.reply({ embeds: [embed] });
        } catch (error) {
            console.error('Files command error:', error);
            await interaction.reply({
                content: 'An error occurred while fetching the file structure.',
                ephemeral: true
            });
        }
    },

    getDirectoryStructure(dir, prefix = '') {
        let structure = '';
        const items = fs.readdirSync(dir);

        items.forEach((item, index) => {
            const isLast = index === items.length - 1;
            const itemPath = path.join(dir, item);
            const stats = fs.statSync(itemPath);

            if (item.startsWith('.') || item === 'node_modules') return;

            structure += `${prefix}${isLast ? '└── ' : '├── '}${item}\n`;

            if (stats.isDirectory()) {
                structure += this.getDirectoryStructure(
                    itemPath,
                    prefix + (isLast ? '    ' : '│   ')
                );
            }
        });

        return structure;
    }
}; 