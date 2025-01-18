const axios = require('axios');

const API_CONFIG = {
    // Animal APIs
    cat: {
        baseUrl: 'https://api.thecatapi.com/v1',
        key: process.env.CAT_API_KEY
    },
    dog: {
        baseUrl: 'https://api.thedogapi.com/v1',
        key: process.env.DOG_API_KEY
    },
    panda: {
        baseUrl: 'https://some-random-api.ml/animal/panda',
        key: null
    },
    fox: {
        baseUrl: 'https://some-random-api.ml/animal/fox',
        key: null
    },
    koala: {
        baseUrl: 'https://some-random-api.ml/animal/koala',
        key: null
    },
    
    // Fact APIs for different categories
    facts: {
        baseUrl: 'https://api.facts.ninja/v1',
        key: process.env.FACTS_API_KEY,
        categories: ['today', 'science', 'history', 'space', 'nature', 'tech']
    },
    
    // Weather API
    weather: {
        baseUrl: 'https://api.openweathermap.org/data/2.5',
        key: process.env.OPENWEATHER_API_KEY
    },
    
    // News API
    news: {
        baseUrl: 'https://newsapi.org/v2',
        key: process.env.NEWS_API_KEY
    },
    
    // Crypto API
    crypto: {
        baseUrl: 'https://pro-api.coinmarketcap.com/v1',
        key: process.env.COINMARKETCAP_API_KEY
    },
    
    // Joke API
    joke: {
        baseUrl: 'https://v2.jokeapi.dev',
        key: process.env.JOKE_API_KEY
    }
};

async function fetchAPI(apiName, endpoint, options = {}) {
    const config = API_CONFIG[apiName];
    if (!config) {
        throw new Error(`API configuration for ${apiName} is missing.`);
    }

    try {
        const url = `${config.baseUrl}${endpoint}`;
        const response = await axios.get(url, {
            headers: {
                ...options.headers,
                ...(config.key && { 'x-api-key': config.key })
            },
            params: {
                ...options.params,
                ...(config.key && { api_key: config.key })
            },
        });
        return response.data;
    } catch (error) {
        console.error(`Error fetching data from ${apiName}:`, error.message);
        throw error;
    }
}

module.exports = { fetchAPI };
