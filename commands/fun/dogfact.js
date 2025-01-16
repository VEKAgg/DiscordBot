const facts = [
    'Dogs have a sense of time and can predict future events like regular walk times.',
    'Dogs have three eyelids.',
    'A dog’s nose print is as unique as a human fingerprint.',
    'Dogs are as smart as a two-year-old child.',
    'The Basenji dog is known as the “barkless dog.”',
  ];
  
  module.exports = {
    name: 'dogfact',
    description: 'Send a random dog fact.',
    execute(message) {
      const fact = facts[Math.floor(Math.random() * facts.length)];
      message.channel.send(`🐶 Dog Fact: ${fact}`);
    },
  };
  