const jwt = require('jsonwebtoken');
const { logger } = require('../../utils/logger');

const authenticateToken = (req, res, next) => {
    try {
        const authHeader = req.headers['authorization'];
        const token = authHeader && authHeader.split(' ')[1];

        if (!token) {
            return res.status(401).json({ 
                success: false, 
                message: 'Authentication token required' 
            });
        }

        jwt.verify(token, process.env.JWT_SECRET, (err, user) => {
            if (err) {
                return res.status(403).json({ 
                    success: false, 
                    message: 'Invalid or expired token' 
                });
            }
            req.user = user;
            next();
        });
    } catch (error) {
        logger.error('Auth Middleware Error:', error);
        res.status(500).json({ 
            success: false, 
            message: 'Authentication error' 
        });
    }
};

const checkGuildPermission = async (req, res, next) => {
    try {
        const { guildId } = req.params;
        const guild = req.user.guilds.find(g => g.id === guildId);

        if (!guild || !(guild.permissions & 0x8)) { // Check for ADMINISTRATOR permission
            return res.status(403).json({
                success: false,
                message: 'Insufficient permissions for this guild'
            });
        }
        next();
    } catch (error) {
        logger.error('Guild Permission Check Error:', error);
        res.status(500).json({
            success: false,
            message: 'Error checking guild permissions'
        });
    }
};

module.exports = { authenticateToken, checkGuildPermission }; 