const { User } = require('../database');

module.exports = {
    name: 'guildMemberRemove',
    async execute(member) {
        try {
            const stats = await User.findOne({
                guildId: member.guild.id,
                type: 'welcome_stats'
            });

            if (stats?.members) {
                const joinRecord = stats.members.find(m => m.userId === member.id);
                if (joinRecord) {
                    joinRecord.leftAt = new Date();
                    joinRecord.duration = joinRecord.leftAt - joinRecord.joinedAt;
                    await stats.save();
                }
            }
        } catch (error) {
            console.error('Error tracking member leave:', error);
        }
    }
}; 