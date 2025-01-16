module.exports = {
    name: 'lmgtfy',
    description: 'Generate a "Let Me Google That For You" link.',
    args: true,
    usage: '<query>',
    execute(message, args) {
      const query = args.join('+');
      const url = `https://lmgtfy.app/?q=${query}`;
      message.reply(`Here you go: ${url}`);
    },
  };
  