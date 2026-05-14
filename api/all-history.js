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
    const limit = parseInt(req.query.limit) || 100;
    const data = generateHistoricalData();
    const limited = data.slice(-limit);
    res.status(200).json(limited);
  } catch (error) {
    console.error('API error:', error);
    res.status(500).json({ error: error.message });
  }
};
