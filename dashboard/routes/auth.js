const express = require('express');
const router = express.Router();
const fetch = require('node-fetch');
const jwt = require('jsonwebtoken');
const { logger } = require('../../utils/logger');

const DISCORD_API = 'https://discord.com/api/v10';

router.post('/login', async (req, res) => {
    try {
        const { code } = req.body;

        // Exchange code for access token
        const tokenResponse = await fetch(`${DISCORD_API}/oauth2/token`, {
            method: 'POST',
            body: new URLSearchParams({
                client_id: process.env.CLIENT_ID,
                client_secret: process.env.CLIENT_SECRET,
                code,
                grant_type: 'authorization_code',
                redirect_uri: `${process.env.DASHBOARD_URL}/callback`,
                scope: 'identify guilds'
            }),
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        });

        const tokens = await tokenResponse.json();

        if (!tokenResponse.ok) {
            throw new Error('Failed to get access token');
        }

        // Get user data
        const userResponse = await fetch(`${DISCORD_API}/users/@me`, {
            headers: { Authorization: `Bearer ${tokens.access_token}` }
        });

        const userData = await userResponse.json();

        // Get user's guilds
        const guildsResponse = await fetch(`${DISCORD_API}/users/@me/guilds`, {
            headers: { Authorization: `Bearer ${tokens.access_token}` }
        });

        const guildsData = await guildsResponse.json();

        // Create JWT
        const token = jwt.sign({
            id: userData.id,
            username: userData.username,
            discriminator: userData.discriminator,
            avatar: userData.avatar,
            guilds: guildsData
        }, process.env.JWT_SECRET, { expiresIn: '24h' });

        res.json({
            success: true,
            token,
            user: userData
        });
    } catch (error) {
        logger.error('Auth Error:', error);
        res.status(500).json({
            success: false,
            message: 'Authentication failed'
        });
    }
});

module.exports = router; 