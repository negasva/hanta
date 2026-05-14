const DEMO_COUNTRIES = {
  'Chile':     { lat: -35.6751, lng: -71.5430, confirmed: 98,  suspected: 32, deaths: 18 },
  'Argentina': { lat: -38.4161, lng: -63.6167, confirmed: 112, suspected: 41, deaths: 21 },
  'Peru':      { lat: -9.1900,  lng: -75.0152, confirmed: 74,  suspected: 28, deaths: 15 },
  'Colombia':  { lat: 4.5709,   lng: -74.2973, confirmed: 53,  suspected: 19, deaths: 10 },
  'Bolivia':   { lat: -16.2902, lng: -63.5887, confirmed: 45,  suspected: 14, deaths:  9 },
  'Ecuador':   { lat: -1.8312,  lng: -78.1834, confirmed: 38,  suspected: 11, deaths:  7 },
  'Paraguay':  { lat: -23.4425, lng: -58.4438, confirmed: 27,  suspected:  6, deaths:  5 },
  'Uruguay':   { lat: -32.5228, lng: -55.7658, confirmed: 18,  suspected:  3, deaths:  4 },
  'Brazil':    { lat: -14.2350, lng: -51.9253, confirmed: 14,  suspected:  2, deaths:  2 },
  'Venezuela': { lat: 6.4238,   lng: -66.5897, confirmed:  8,  suspected:  0, deaths:  1 }
};

function getCountries() {
  return Object.entries(DEMO_COUNTRIES).map(([country, data]) => ({
    country,
    latitude: data.lat,
    longitude: data.lng,
    confirmed_cases: data.confirmed,
    suspected_cases: data.suspected,
    deaths: data.deaths
  }));
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
    const data = getCountries();
    res.status(200).json(data);
  } catch (error) {
    console.error('API error:', error);
    res.status(500).json({ error: error.message });
  }
};
