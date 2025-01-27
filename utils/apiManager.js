const fetch = require('node-fetch');
const { logger } = require('./logger');

const API_ENDPOINTS = {
    github: 'https://api.github.com',
};

async function fetchAPI(service, endpoint, options = {}) {
    if (!API_ENDPOINTS[service]) {
        throw new Error(`Unknown API service: ${service}`);
    }

    const url = `${API_ENDPOINTS[service]}${endpoint}`;
    try {
        const response = await fetch(url, {
            headers: {
                'Accept': 'application/json',
                'User-Agent': 'VEKA-Bot',
                ...options.headers
            },
            ...options
        });

        if (!response.ok) {
            throw new Error(`API request failed: ${response.status} ${response.statusText}`);
        }

        return await response.json();
    } catch (error) {
        logger.error(`API Request Error (${service}):`, error);
        throw error;
    }
}

module.exports = { fetchAPI };
