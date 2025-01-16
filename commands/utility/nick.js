module.exports = {
    name: 'nick',
    description: 'Change your nickname.',
    args: true,
    usage: '<nickname>',
    execute(message, args) {
      const nickname = args.join(' ');
  
      if (!message.guild) {
        return message.reply('This command can only be used in a server.');
      }
  
      if (!message.guild.members.me.permissions.has('ManageNicknames')) {
        return message.reply("I don't have permission to change nicknames. Please check my role permissions.");
      }
  
      if (!message.member.permissions.has('ChangeNickname')) {
        return message.reply("You don't have permission to change your nickname.");
      }
  
      message.member.setNickname(nickname)
        .then(() => message.reply(`Nickname changed to: ${nickname}`))
        .catch((error) => {
          console.error(error);
          message.reply('I was unable to change your nickname. This might be due to role hierarchy or missing permissions.');
        });
    },
  };
  