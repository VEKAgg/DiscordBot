const express = require('express');
const router = express.Router();
const voiceTracking = require('../../utils/voiceTracking');
const { authenticateToken } = require('../../middleware/auth');

router.get('/stats/:guildId', authenticateToken, async (req, res) => {
    try {
        const { guildId } = req.params;
        const { timeframe } = req.query;

        const stats = await voiceTracking.getVoiceStats(guildId, timeframe);
        if (!stats) {
            return res.status(404).json({ message: 'No voice stats found' });
        }

        res.json({
            success: true,
            data: {
                ...stats,
                uniqueUsers: stats.uniqueUsers.length,
                avgSessionLength: Math.floor(stats.avgSessionLength / 1000 / 60), // Convert to minutes
                totalDuration: Math.floor(stats.totalDuration / 1000 / 60 / 60) // Convert to hours
            }
        });
    } catch (error) {
        res.status(500).json({ 
            success: false, 
            message: 'Error fetching voice stats',
            error: error.message 
        });
    }
});

module.exports = router; 