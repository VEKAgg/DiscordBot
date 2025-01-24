const axios = require('axios');
const apis = require('../config/apis');
const { logger } = require('./logger');

async function fetchAPI(service, endpoint, options = {}) {
    if (!apis[service]) {
        throw new Error(`API service "${service}" not configured`);
    }

    const config = apis[service];
    let url;

    // Handle special cases for different APIs
    switch (service) {
        case 'cat':
            url = endpoint.includes('images') ? config.imageUrl : `${config.baseUrl}${endpoint}`;
            break;
        case 'dog':
            url = endpoint.includes('images') ? config.imageUrl : 
                  endpoint.includes('facts') ? config.factsUrl : 
                  `${config.baseUrl}${endpoint}`;
            break;
        default:
            url = `${config.baseUrl}${endpoint}`;
    }

    try {
        const response = await axios({
            url,
            method: options.method || 'GET',
            headers: { ...config.headers, ...options.headers },
            params: { ...config.params, ...options.params },
            data: options.data
        });

        // Handle different API response formats
        if (service === 'dog' && endpoint.includes('images')) {
            return { url: response.data.message };
        }

        return response.data;
    } catch (error) {
        logger.error(`API Error (${service}${endpoint}):`, error.message);
        throw error;
    }
}

module.exports = { fetchAPI };
