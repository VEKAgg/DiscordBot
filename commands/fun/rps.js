module.exports = {
    name: 'rps',
    description: 'Play Rock, Paper, Scissors.',
    args: true,
    usage: '<rock/paper/scissors>',
    execute(message, args) {
      const choices = ['rock', 'paper', 'scissors'];
      const userChoice = args[0].toLowerCase();
      const botChoice = choices[Math.floor(Math.random() * choices.length)];
  
      if (!choices.includes(userChoice)) {
        return message.reply(`Invalid choice. Please choose rock, paper, or scissors.`);
      }
  
      let result = '';
      if (userChoice === botChoice) {
        result = 'It’s a tie!';
      } else if (
        (userChoice === 'rock' && botChoice === 'scissors') ||
        (userChoice === 'paper' && botChoice === 'rock') ||
        (userChoice === 'scissors' && botChoice === 'paper')
      ) {
        result = 'You win!';
      } else {
        result = 'I win!';
      }
  
      message.reply(`You chose ${userChoice}, I chose ${botChoice}. ${result}`);
    },
  };
  