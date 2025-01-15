const fs = require('fs');
const path = require('path');

module.exports = {
    name: 'structure',
    description: 'Displays the folder structure of the bot.',
    execute(message) {
        const getStructure = (dir, depth = 0) => {
            const indent = ' '.repeat(depth * 2);
            const files = fs.readdirSync(dir);

            return files
                .map((file) => {
                    const fullPath = path.join(dir, file);
                    if (fs.statSync(fullPath).isDirectory()) {
                        return `${indent}${file}/\n${getStructure(fullPath, depth + 1)}`;
                    }
                    return `${indent}${file}`;
                })
                .join('\n');
        };

        const structure = getStructure('./');
        message.channel.send({
            embeds: [
                {
                    title: 'Folder Structure',
                    description: `\`\`\`${structure}\`\`\``,
                    color: 0xFFA500,
                },
            ],
        });
    },
};
