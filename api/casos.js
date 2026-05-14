const DEMO_COUNTRIES = {
  'Chile':     { confirmed: 98,  suspected: 32, deaths: 18 },
  'Argentina': { confirmed: 112, suspected: 41, deaths: 21 },
  'Peru':      { confirmed: 74,  suspected: 28, deaths: 15 },
  'Colombia':  { confirmed: 53,  suspected: 19, deaths: 10 },
  'Bolivia':   { confirmed: 45,  suspected: 14, deaths:  9 },
  'Ecuador':   { confirmed: 38,  suspected: 11, deaths:  7 },
  'Paraguay':  { confirmed: 27,  suspected:  6, deaths:  5 },
  'Uruguay':   { confirmed: 18,  suspected:  3, deaths:  4 },
  'Brazil':    { confirmed: 14,  suspected:  2, deaths:  2 },
  'Venezuela': { confirmed:  8,  suspected:  0, deaths:  1 }
};

function getLatestStats() {
  const total = Object.values(DEMO_COUNTRIES).reduce((acc, country) => ({
    confirmed: acc.confirmed + country.confirmed,
    suspected: acc.suspected + country.suspected,
    deaths: acc.deaths + country.deaths
  }), { confirmed: 0, suspected: 0, deaths: 0 });

  return {
    timestamp: new Date().toISOString(),
    confirmed_cases: total.confirmed,
    suspected_cases: total.suspected,
    deaths: total.deaths,
    affected_countries: Object.keys(DEMO_COUNTRIES),
    source: 'Demo Data'
  };
}

module.exports = (req, res) => {
  res.setHeader('Access-Control-Allow-Credentials', 'true');
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS,PATCH,DELETE,POST,PUT');
  res.setHeader('Access-Control-Allow-Headers', 'X-CSRF-Token, X-Requested-With, Accept, Accept-Version, Content-Length, Content-MD5, Content-Type, Date, X-Api-Version');

  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }

  try {
    const data = getLatestStats();
    res.status(200).json(data);
  } catch (error) {
    console.error('API error:', error);
    res.status(500).json({ error: error.message });
  }
};
