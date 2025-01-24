const { EmbedBuilder } = require('discord.js');

module.exports = {
    name: 'serverinfo',
    description: 'Display server information',
    async execute(message) {
        const guild = message.guild;
        const owner = await guild.fetchOwner();
        
        const embed = new EmbedBuilder()
            .setTitle(`${guild.name} Server Information`)
            .setThumbnail(guild.iconURL({ dynamic: true }))
            .addFields([
                { name: 'Owner', value: owner.user.tag, inline: true },
                { name: 'Members', value: guild.memberCount.toString(), inline: true },
                { name: 'Channels', value: guild.channels.cache.size.toString(), inline: true },
                { name: 'Roles', value: guild.roles.cache.size.toString(), inline: true },
                { name: 'Created At', value: guild.createdAt.toLocaleDateString(), inline: true },
                { name: 'Boost Level', value: guild.premiumTier.toString(), inline: true }
            ])
            .setColor('#0099ff');

        message.channel.send({ embeds: [embed] });
    }
};
