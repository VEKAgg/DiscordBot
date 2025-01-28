const footers = [
    'advertise your server here',
    'veka estd 2024',
    'veka.gg',
    'join us',
    // Add joke footers for specific commands
    'this is a joke',
    'don\'t take this seriously'
];

function getRandomFooter() {
    return footers[Math.floor(Math.random() * footers.length)];
}

module.exports = { getRandomFooter }; 