module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Credentials', 'true');
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS,PATCH,DELETE,POST,PUT');
  res.setHeader('Access-Control-Allow-Headers', 'X-CSRF-Token, X-Requested-With, Accept, Accept-Version, Content-Length, Content-MD5, Content-Type, Date, X-Api-Version');

  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }

  try {
    const supabaseUrl = process.env.SUPABASE_URL;
    const supabaseKey = process.env.SUPABASE_ANON_KEY;

    if (!supabaseUrl || !supabaseKey) {
      throw new Error('Supabase credentials not configured');
    }

    const response = await fetch(
      `${supabaseUrl}/rest/v1/country_data?select=*&order=timestamp.desc`,
      {
        headers: {
          'Authorization': `Bearer ${supabaseKey}`,
          'apikey': supabaseKey,
          'Content-Type': 'application/json'
        }
      }
    );

    if (!response.ok) {
      throw new Error(`Supabase error: ${response.status}`);
    }

    const rows = await response.json();

    // Get latest data per country
    const latestByCountry = {};
    rows.forEach(row => {
      if (!latestByCountry[row.country] ||
          new Date(row.timestamp) > new Date(latestByCountry[row.country].timestamp)) {
        latestByCountry[row.country] = row;
      }
    });

    const data = Object.values(latestByCountry).map(row => ({
      country: row.country,
      latitude: row.latitude,
      longitude: row.longitude,
      confirmed_cases: row.confirmed_cases,
      suspected_cases: row.suspected_cases,
      deaths: row.deaths
    }));

    res.status(200).json(data);
  } catch (error) {
    console.error('API error:', error);
    res.status(500).json({ error: error.message });
  }
};
