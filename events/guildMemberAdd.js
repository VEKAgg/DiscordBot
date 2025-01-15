module.exports = {
    name: 'guildMemberAdd',
    execute(member, client) {
        if (!client.loggingChannel) return;

        const channel = member.guild.channels.cache.get(client.loggingChannel);
        if (!channel) return;

        const embed = {
            title: 'New Member Joined',
            description: `${member.user.tag} joined the server.`,
            color: 0x00FF00, // Green
        };
        channel.send({ embeds: [embed] });
    },
};
