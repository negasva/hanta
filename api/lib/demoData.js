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
    source: 'Demo Data (External sources unavailable)'
  };
}

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

function generateHistoricalData() {
  const now = new Date();
  const data = [];

  for (let i = 20; i >= 0; i--) {
    const timestamp = new Date(now.getTime() - i * 60 * 60 * 1000);
    const multiplier = 1 - (i / 20) * 0.3;

    data.push({
      timestamp: timestamp.toISOString(),
      confirmed_cases: Math.floor(487 * multiplier),
      suspected_cases: Math.floor(156 * multiplier),
      deaths: Math.floor(92 * multiplier)
    });
  }

  return data;
}

module.exports = {
  DEMO_COUNTRIES,
  getLatestStats,
  getCountries,
  generateHistoricalData
};
