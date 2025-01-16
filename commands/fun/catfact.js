const facts = [
    'Cats sleep for 70% of their lives.',
    'A group of cats is called a clowder.',
    'Cats can rotate their ears 180 degrees.',
    'A cat’s nose is as unique as a human’s fingerprint.',
    'Domestic cats share about 95.6% of their DNA with tigers.',
  ];
  
  module.exports = {
    name: 'catfact',
    description: 'Send a random cat fact.',
    execute(message) {
      const fact = facts[Math.floor(Math.random() * facts.length)];
      message.channel.send(`🐱 Cat Fact: ${fact}`);
    },
  };
  