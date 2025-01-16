const fetch = require('node-fetch');
const { EmbedBuilder } = require('discord.js');

module.exports = {
  name: 'weather',
  description: 'Get the current weather for a specific city.',
  args: true,
  usage: '<city>',
  async execute(message, args) {
    const city = args.join(' ');
    const apiKey = 'YOUR_OPENWEATHER_API_KEY'; // Replace with your valid OpenWeather API key.
    const url = `https://api.openweathermap.org/data/2.5/weather?q=${encodeURIComponent(city)}&appid=${apiKey}&units=metric`;

    try {
      const response = await fetch(url);
      const data = await response.json();

      if (data.cod !== 200) {
        return message.reply(`Could not find weather data for "${city}". Error: ${data.message}`);
      }

      const embed = new EmbedBuilder()
        .setTitle(`Weather in ${data.name}`)
        .setDescription(data.weather[0].description)
        .
