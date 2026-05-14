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
    const limit = parseInt(req.query.limit) || 100;

    if (!supabaseUrl || !supabaseKey) {
      throw new Error('Supabase credentials not configured');
    }

    const response = await fetch(
      `${supabaseUrl}/rest/v1/outbreak_data?select=*&order=timestamp.asc&limit=${limit}`,
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

    const formatted = data.map(record => ({
      timestamp: record.timestamp,
      confirmed_cases: record.confirmed_cases,
      suspected_cases: record.suspected_cases,
      deaths: record.deaths
    }));

    res.status(200).json(formatted);
  } catch (error) {
    console.error('API error:', error);
    res.status(500).json({ error: error.message });
  }
};
