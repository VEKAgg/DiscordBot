const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const morgan = require('morgan');
const rateLimit = require('express-rate-limit');
const { logger } = require('../utils/logger');

// Import routes
const authRoutes = require('./routes/auth');
const guildRoutes = require('./routes/guilds');
const statsRoutes = require('./routes/stats');
const voiceRoutes = require('./routes/api/voiceStats');

const app = express();

// Security middleware
app.use(helmet());
app.use(cors({
    origin: process.env.DASHBOARD_URL,
    credentials: true
}));

// Rate limiting
const limiter = rateLimit({
    windowMs: 15 * 60 * 1000, // 15 minutes
    max: 100 // limit each IP to 100 requests per windowMs
});
app.use('/api/', limiter);

// Logging and parsing
app.use(morgan('combined', { stream: { write: message => logger.info(message.trim()) } }));
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Routes
app.use('/api/auth', authRoutes);
app.use('/api/guilds', guildRoutes);
app.use('/api/stats', statsRoutes);
app.use('/api/voice', voiceRoutes);

// Error handling
app.use((err, req, res, next) => {
    logger.error('Dashboard Error:', err);
    res.status(err.status || 500).json({
        success: false,
        message: err.message || 'Internal server error',
        error: process.env.NODE_ENV === 'development' ? err : {}
    });
});

module.exports = app; 