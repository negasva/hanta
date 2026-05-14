const express = require('express');
const cors = require('cors');
const bodyParser = require('body-parser');
const cron = require('node-cron');
const path = require('path');

const {
  initializeDatabase,
  getLatestData,
  getHistoricalData,
  getCountryData,
  getAllHistoricalData,
  clearOldData
} = require('./db');
const { scrapeAllSources } = require('./scraper');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));
app.use(express.static('public'));

// Initialize database
initializeDatabase().catch(err => {
  console.error('Failed to initialize database:', err);
  process.exit(1);
});

// Initial scrape on startup
console.log('Performing initial scrape...');
scrapeAllSources().catch(console.error);

// Schedule scraping every hour
cron.schedule('0 * * * *', async () => {
  console.log(`[${new Date().toISOString()}] Scheduled scrape starting...`);
  try {
    await scrapeAllSources();
  } catch (error) {
    console.error('Scheduled scrape error:', error.message);
  }
});

// Clean old data daily
cron.schedule('0 0 * * *', async () => {
  console.log('Cleaning old data...');
  try {
    await clearOldData(30);
    console.log('Data cleanup completed');
  } catch (error) {
    console.error('Cleanup error:', error.message);
  }
});

// API Endpoints

// GET latest cases data
app.get('/api/casos', async (req, res) => {
  try {
    const data = await getLatestData();
    if (!data) {
      return res.status(404).json({ error: 'No data available' });
    }

    const affectedCountries = JSON.parse(data.affected_countries || '[]');
    res.json({
      timestamp: data.timestamp,
      confirmed_cases: data.confirmed_cases,
      suspected_cases: data.suspected_cases,
      deaths: data.deaths,
      affected_countries: affectedCountries,
      source: data.source
    });
  } catch (error) {
    console.error('API error:', error);
    res.status(500).json({ error: error.message });
  }
});

// GET historical data
app.get('/api/historial', async (req, res) => {
  try {
    const hours = parseInt(req.query.hours) || 24;
    const data = await getHistoricalData(hours);

    const formatted = data.map(record => ({
      timestamp: record.timestamp,
      confirmed_cases: record.confirmed_cases,
      suspected_cases: record.suspected_cases,
      deaths: record.deaths
    }));

    res.json(formatted);
  } catch (error) {
    console.error('API error:', error);
    res.status(500).json({ error: error.message });
  }
});

// GET affected countries with coordinates
app.get('/api/paises', async (req, res) => {
  try {
    const data = await getCountryData();
    res.json(data);
  } catch (error) {
    console.error('API error:', error);
    res.status(500).json({ error: error.message });
  }
});

// GET all historical data (for charting)
app.get('/api/all-history', async (req, res) => {
  try {
    const limit = parseInt(req.query.limit) || 100;
    const data = await getAllHistoricalData(limit);

    const formatted = data.reverse().map(record => ({
      timestamp: record.timestamp,
      confirmed_cases: record.confirmed_cases,
      suspected_cases: record.suspected_cases,
      deaths: record.deaths
    }));

    res.json(formatted);
  } catch (error) {
    console.error('API error:', error);
    res.status(500).json({ error: error.message });
  }
});

// Manual trigger scrape endpoint (for testing)
app.post('/api/scrape', async (req, res) => {
  try {
    const result = await scrapeAllSources();
    res.json({ success: true, data: result });
  } catch (error) {
    console.error('Manual scrape error:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Health check
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Serve index.html for any unmatched routes
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, '../public/index.html'));
});

// Start server
app.listen(PORT, () => {
  console.log(`
╔════════════════════════════════════════╗
║  Hantavirus Monitoring Application    ║
║  Andes Outbreak Tracker (MV Hondius)  ║
╚════════════════════════════════════════╝

Server running on http://localhost:${PORT}
API available at http://localhost:${PORT}/api/

Endpoints:
  GET  /api/casos        - Latest case data
  GET  /api/historial    - Historical data (24h default)
  GET  /api/paises       - Affected countries with coordinates
  GET  /api/all-history  - All historical records
  POST /api/scrape       - Trigger manual scrape (testing)
  GET  /api/health       - Health check

Scraping schedule: Every hour
Data cleanup: Daily at midnight (keeps 30 days)
  `);
});

module.exports = app;
