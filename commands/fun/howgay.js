module.exports = {
    name: 'howgay',
    description: 'Find out how "gay" someone is (for humor).',
    args: false,
    usage: '[user]',
    execute(message, args) {
      const target = message.mentions.users.first() || message.author;
      const percentage = Math.floor(Math.random() * 101);
  
      message.reply(`${target.username} is ${percentage}% gay 🏳️‍🌈`);
    },
  };
  