const { EmbedBuilder } = require('discord.js');
const { fetchAPI } = require('../../utils/apiManager');
const moment = require('moment-timezone');

module.exports = {
  name: 'weather',
  description: 'Get detailed weather information for a city',
  async execute(message, args) {
    if (!args.length) return message.reply('Please provide a city name!');
    
    const city = args.join(' ');
    try {
      const weather = await fetchAPI('weather', `/weather`, {
        params: {
          q: city,
          units: 'metric'
        }
      });

      const forecast = await fetchAPI('weather', `/forecast`, {
        params: {
          q: city,
          units: 'metric',
          cnt: 3 // 3-day forecast
        }
      });

      const embed = new EmbedBuilder()
        .setTitle(`Weather in ${weather.name}, ${weather.sys.country}`)
        .setDescription(`**${weather.weather[0].main}:** ${weather.weather[0].description}`)
        .addFields([
          { name: 'Temperature', value: `${Math.round(weather.main.temp)}°C`, inline: true },
          { name: 'Feels Like', value: `${Math.round(weather.main.feels_like)}°C`, inline: true },
          { name: 'Humidity', value: `${weather.main.humidity}%`, inline: true },
          { name: 'Wind', value: `${weather.wind.speed} m/s`, inline: true },
          { name: 'Pressure', value: `${weather.main.pressure} hPa`, inline: true },
          { name: 'Visibility', value: `${weather.visibility / 1000} km`, inline: true },
          { name: 'Forecast', value: forecast.list.map(day => 
            `${moment.unix(day.dt).format('DD/MM')}: ${Math.round(day.main.temp)}°C - ${day.weather[0].main}`
          ).join('\n')}
        ])
        .setThumbnail(`http://openweathermap.org/img/w/${weather.weather[0].icon}.png`)
        .setColor('#0099ff')
        .setTimestamp();

      message.channel.send({ embeds: [embed] });
    } catch (error) {
      message.reply('Could not find weather information for that city!');
    }
  },
};
