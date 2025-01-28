module.exports = {
    channelId: 'YOUR_DASHBOARD_CHANNEL_ID',
    updateInterval: '*/10 * * * *', // Every 10 minutes
    messageIds: {
        overall: null,    // Set these IDs after first creation
        gaming: null,     // or load from database
        voice: null,
        text: null,
        github: null,
        welcome: null
    },
    embedSettings: {
        overall: { 
            title: '🏆 Server Activity Overview',
            color: '#FFD700'
        },
        gaming: { 
            title: '🎮 Top Gamers',
            color: '#7289DA'
        },
        voice: { 
            title: '🎤 Voice Champions',
            color: '#2ECC71'
        },
        text: { 
            title: '💬 Chat Leaders',
            color: '#3498DB'
        },
        github: {
            title: '🤖 Bot Updates',
            color: '#2b2d31'
        },
        welcome: {
            title: '📊 Server Insights',
            color: '#00ff00'
        }
    }
}; 