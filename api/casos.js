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
      `${supabaseUrl}/rest/v1/outbreak_data?select=*&order=timestamp.desc&limit=1`,
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

    const data = await response.json();

    if (!data || data.length === 0) {
      return res.status(404).json({ error: 'No data available' });
    }

    const latest = data[0];
    const affectedCountries = typeof latest.affected_countries === 'string'
      ? JSON.parse(latest.affected_countries)
      : latest.affected_countries || [];

    res.status(200).json({
      timestamp: latest.timestamp,
      confirmed_cases: latest.confirmed_cases,
      suspected_cases: latest.suspected_cases,
      deaths: latest.deaths,
      affected_countries: affectedCountries,
      source: latest.source
    });
  } catch (error) {
    console.error('API error:', error);
    res.status(500).json({ error: error.message });
  }
};
