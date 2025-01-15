const { Client, GatewayIntentBits } = require('discord.js');
require('dotenv').config(); // To securely load the token from .env

// Create a new Discord client
const client = new Client({
    intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent],
});

// Event: Bot is ready
client.once('ready', () => {
    console.log(`Logged in as ${client.user.tag}!`);
});

// Event: Respond to messages
client.on('messageCreate', (message) => {
    if (message.author.bot) return; // Ignore bot messages
    if (message.content === '!ping') {
        message.reply('Pong!');
    }
});

// Log in the bot using the token from .env
client.login(process.env.TOKEN);
