module.exports = {
    apis: {
        weather: {
            key: process.env.OPENWEATHER_API_KEY,
            baseUrl: 'https://api.openweathermap.org/data/2.5'
        },
        news: {
            key: process.env.NEWS_API_KEY,
            baseUrl: 'https://newsapi.org/v2'
        },
        crypto: {
            key: process.env.COINMARKETCAP_API_KEY,
            baseUrl: 'https://pro-api.coinmarketcap.com/v1'
        },
        cat: {
            key: process.env.CAT_API_KEY,
            baseUrl: 'https://api.thecatapi.com/v1'
        },
        dog: {
            key: process.env.DOG_API_KEY,
            baseUrl: 'https://api.thedogapi.com/v1'
        },
        joke: {
            key: process.env.JOKE_API_KEY,
            baseUrl: 'https://v2.jokeapi.dev'
        },
        github: {
            key: process.env.GITHUB_TOKEN,
            baseUrl: 'https://api.github.com'
        }
    }
};
