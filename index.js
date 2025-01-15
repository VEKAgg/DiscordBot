const { Client, GatewayIntentBits, Collection } = require('discord.js');
const fs = require('fs');
require('dotenv').config();

const client = new Client({
    intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent, GatewayIntentBits.GuildPresences],
});

client.commands = new Collection();

// Load commands
const loadCommands = (dir) => {
    const commandFiles = fs.readdirSync(dir).filter((file) => file.endsWith('.js'));
    for (const file of commandFiles) {
        console.log(`Loading command: ${file}`);
        const command = require(`${dir}/${file}`);
        client.commands.set(command.name, command);
    }

    const subfolders = fs.readdirSync(dir).filter((folder) => fs.lstatSync(`${dir}/${folder}`).isDirectory());
    for (const subfolder of subfolders) {
        loadCommands(`${dir}/${subfolder}`); // Recursively load subfolders
    }
};

loadCommands('./commands');


// Load events
const eventFiles = fs.readdirSync('./events').filter((file) => file.endsWith('.js'));
for (const file of eventFiles) {
    console.log(`Loading event: ${file}`);
    const event = require(`./events/${file}`);
    if (event.once) {
        client.once(event.name, (...args) => event.execute(...args, client));
    } else {
        client.on(event.name, (...args) => event.execute(...args, client));
    }
}

// Login the bot
client.login(process.env.TOKEN);

client.points = new Map();

