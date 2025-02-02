const { ActivityType } = require('discord.js');
const { joinVoiceChannel } = require('@discordjs/voice');
const { logger } = require('../utils/logger');
const config = require('../config/botStatus');
const { REST, Routes } = require('discord.js');

module.exports = {
    name: 'ready',
    once: true,
    async execute(client) {
        try {
            logger.info(`Logged in as ${client.user.tag}`);

            // Get all slash commands
            const commands = [];
            client.slashCommands.forEach(command => {
                if (command.slashCommand) {
                    commands.push(command.slashCommand.toJSON());
                }
            });

            // Register slash commands
            const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);
            
            logger.info(`Started refreshing ${commands.length} application (/) commands.`);

            try {
                await rest.put(
                    Routes.applicationCommands(client.user.id),
                    { body: commands }
                );
                logger.info('Successfully reloaded application (/) commands.');
            } catch (error) {
                logger.error('Failed to register slash commands:', error);
            }

            // Join voice channel if configured
            if (process.env.HOME_VOICE_CHANNEL && process.env.HOME_GUILD_ID) {
                try {
                    const guild = client.guilds.cache.get(process.env.HOME_GUILD_ID);
                    if (guild) {
                        joinVoiceChannel({
                            channelId: process.env.HOME_VOICE_CHANNEL,
                            guildId: process.env.HOME_GUILD_ID,
                            adapterCreator: guild.voiceAdapterCreator,
                            selfDeaf: true
                        });
                        logger.info('Successfully joined home voice channel');
                    } else {
                        logger.warn('Home guild not found');
                    }
                } catch (error) {
                    logger.error('Failed to join voice channel:', error);
                }
            }

            // Initialize status rotation
            let statusIndex = 0;
            setInterval(() => {
                const status = config.statuses[statusIndex];
                let text = status.text
                    .replace('{memberCount}', client.users.cache.size)
                    .replace('{serverCount}', client.guilds.cache.size)
                    .replace('{activeVoice}', client.voice.adapters.size);

                client.user.setPresence({
                    activities: [{ name: text, type: status.type }],
                    status: 'online'
                });
                statusIndex = (statusIndex + 1) % config.statuses.length;
            }, config.interval);

        } catch (error) {
            logger.error('Error in ready event:', error);
        }
    }
};
