const formatTime = (ms) => {
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    return {
        days,
        hours: hours % 24,
        minutes: minutes % 60,
        seconds: seconds % 60
    };
};

const formatStats = (stats, timeframe = 'all') => {
    if (!stats) return '0';
    
    switch (timeframe) {
        case 'day':
            return stats.daily?.toString() || '0';
        case 'week':
            return stats.weekly?.toString() || '0';
        case 'month':
            return stats.monthly?.toString() || '0';
        default:
            return stats.total?.toString() || '0';
    }
};

module.exports = {
    formatTime,
    formatStats
}; 