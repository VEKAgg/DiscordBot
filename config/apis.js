module.exports = {
    quotes: {
        baseUrl: 'https://api.quotable.io',
        headers: {
            'Accept': 'application/json'
        }
    },
    facts: {
        baseUrl: 'https://uselessfacts.jsph.pl/api',
        params: {
            language: 'en'
        }
    },
    cat: {
        baseUrl: 'https://cat-fact.herokuapp.com',
        imageUrl: 'https://api.thecatapi.com/v1/images/search',
        headers: {
            'x-api-key': process.env.CAT_API_KEY
        }
    },
    dog: {
        baseUrl: 'https://dog.ceo/api',
        factsUrl: 'https://dog-api.kinduff.com/api/facts',
        imageUrl: 'https://api.thedogapi.com/v1/images/search',
        headers: {
            'x-api-key': process.env.DOG_API_KEY
        }
    },
    reddit: {
        baseUrl: 'https://www.reddit.com',
        params: {
            raw_json: 1
        }
    },
    github: {
        baseUrl: 'https://api.github.com',
        headers: {
            'Authorization': `token ${process.env.GITHUB_TOKEN}`,
            'Accept': 'application/vnd.github.v3+json'
        }
    },
    weather: {
        baseUrl: 'https://api.openweathermap.org/data/2.5',
        params: {
            appid: process.env.WEATHER_API_KEY,
            units: 'metric'
        }
    }
}; 