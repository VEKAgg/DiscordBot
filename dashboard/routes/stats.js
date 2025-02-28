const express = require('express');
const router = express.Router();
const { authenticateToken, checkGuildPermission } = require('../middleware/auth');
const Analytics = require('../../utils/analytics');
const voiceTracking = require('../../utils/voiceTracking');
const { logger } = require('../../utils/logger');

router.get('/overview/:guildId', authenticateToken, checkGuildPermission, async (req, res) => {
    try {
        const { guildId } = req.params;
        const { timeframe } = req.query;

        const [generalStats, voiceStats] = await Promise.all([
            Analytics.getStats(guildId, 'overview', timeframe),
            voiceTracking.getVoiceStats(guildId, timeframe)
        ]);

        res.json({
            success: true,
            data: {
                general: generalStats,
                voice: voiceStats
            }
        });
    } catch (error) {
        logger.error('Stats Overview Error:', error);
        res.status(500).json({
            success: false,
            message: 'Error fetching stats overview'
        });
    }
});

module.exports = router; 