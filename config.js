const { GatewayIntentBits } = require('discord.js');
const v8 = require('v8');
v8.setFlagsFromString('--max-old-space-size=512'); // Limit heap size

const config = {
    intents: [
      GatewayIntentBits.Guilds,
      GatewayIntentBits.GuildMessages,
      GatewayIntentBits.MessageContent,
      GatewayIntentBits.GuildPresences,
      GatewayIntentBits.GuildMembers
    ],
    maxListeners: 15,
    richPresence: {
      activities: [
        {
          name: 'your server!',
          type: 'WATCHING', // Can also be PLAYING, LISTENING, STREAMING
        },
        {
          name: 'for commands!',
          type: 'LISTENING',
        },
        {
          name: 'call',
          type: 'COMPETING',
          // This will be dynamically updated when bot joins VC
        }
      ],
      status: 'online',
      homeGuildId: '1088553066334273537', // Your server ID
      homeVoiceId: '1088553067554799809'  // Your voice channel ID
    },
    botDescription: 'A multi-purpose bot with utility, fun, and informational commands!',
    scheduledTaskCron: '0 * * * *', // Every hour as an example
    channels: {
        welcome: 'CHANNEL_ID',
        rules: 'CHANNEL_ID',
        roles: 'CHANNEL_ID',
        introductions: 'CHANNEL_ID',
        gaming: 'CHANNEL_ID',
        lfg: 'CHANNEL_ID',
        highlights: 'CHANNEL_ID'
    },
    roles: {
        member: 'ROLE_ID',
        verified: 'ROLE_ID',
        unverified: 'ROLE_ID',
        suspicious: 'ROLE_ID'
    },
    welcomeBanner: 'BANNER_URL',

    // Add environment-specific configurations
    environment: process.env.NODE_ENV || 'development',
    
    // Add rate limiting configurations
    rateLimits: {
        commands: {
            windowMs: 60000,
            max: 10
        },
        api: {
            windowMs: 300000,
            max: 100
        }
    },

    // Add error messages
    errorMessages: {
        rateLimited: 'Please wait {time} before using this command again.',
        missingPermissions: 'You don\'t have permission to use this command.',
        apiError: 'External service is currently unavailable.'
    },

    // Add feature flags
    features: {
        enableAnalytics: true,
        enableLogging: true,
        maintenanceMode: false
    },

    // Add system-specific settings
    system: {
        maxConcurrentProcesses: require('os').cpus().length,
        memoryLimit: process.env.NODE_ENV === 'production' ? '512MB' : '256MB',
        tempDir: '/tmp/veka-bot', // Linux temp directory
        logRotation: {
            enabled: true,
            interval: '1d',
            maxFiles: 7
        }
    },

    // Add performance monitoring
    monitoring: {
        enabled: true,
        interval: 300000, // 5 minutes
        metrics: ['cpu', 'memory', 'latency']
    },

    // Add caching strategy
    cache: {
        commands: { ttl: 3600 }, // 1 hour
        analytics: { ttl: 300 }, // 5 minutes
        userProfiles: { ttl: 1800 } // 30 minutes
    }
};

// Add validation
Object.freeze(config);
module.exports = config;

process.on('memory', () => {
    const used = process.memoryUsage();
    logger.info(`Memory usage: ${Math.round(used.heapUsed / 1024 / 1024)}MB`);
});
