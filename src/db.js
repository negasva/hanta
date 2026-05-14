const Database = require('better-sqlite3');
const path = require('path');

const dbPath = path.join(__dirname, '../data/hantavirus.db');
const db = new Database(dbPath);

db.pragma('journal_mode = WAL');

function initializeDatabase() {
  db.exec(`
    CREATE TABLE IF NOT EXISTS outbreak_data (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
      confirmed_cases INTEGER,
      suspected_cases INTEGER,
      deaths INTEGER,
      affected_countries TEXT,
      source TEXT
    );

    CREATE TABLE IF NOT EXISTS country_data (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
      country TEXT NOT NULL,
      latitude REAL NOT NULL,
      longitude REAL NOT NULL,
      confirmed_cases INTEGER,
      suspected_cases INTEGER,
      deaths INTEGER
    );

    CREATE INDEX IF NOT EXISTS idx_outbreak_timestamp ON outbreak_data(timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_country_timestamp ON country_data(timestamp DESC);
  `);
}

function getLatestData() {
  const stmt = db.prepare(`
    SELECT * FROM outbreak_data
    ORDER BY timestamp DESC
    LIMIT 1
  `);
  return stmt.get();
}

function getHistoricalData(hours = 24) {
  const stmt = db.prepare(`
    SELECT * FROM outbreak_data
    WHERE timestamp > datetime('now', '-' || ? || ' hours')
    ORDER BY timestamp ASC
  `);
  return stmt.all(hours);
}

function getCountryData() {
  const stmt = db.prepare(`
    SELECT DISTINCT
      country,
      latitude,
      longitude,
      SUM(confirmed_cases) as confirmed_cases,
      SUM(suspected_cases) as suspected_cases,
      SUM(deaths) as deaths
    FROM country_data
    WHERE timestamp = (SELECT MAX(timestamp) FROM country_data)
    GROUP BY country
    ORDER BY confirmed_cases DESC
  `);
  return stmt.all();
}

function insertOutbreakData(data) {
  const stmt = db.prepare(`
    INSERT INTO outbreak_data (confirmed_cases, suspected_cases, deaths, affected_countries, source)
    VALUES (?, ?, ?, ?, ?)
  `);
  return stmt.run(
    data.confirmed_cases || 0,
    data.suspected_cases || 0,
    data.deaths || 0,
    JSON.stringify(data.affected_countries || []),
    data.source || 'unknown'
  );
}

function insertCountryData(countryName, lat, lng, cases) {
  const stmt = db.prepare(`
    INSERT INTO country_data (country, latitude, longitude, confirmed_cases, suspected_cases, deaths)
    VALUES (?, ?, ?, ?, ?, ?)
  `);
  return stmt.run(
    countryName,
    lat,
    lng,
    cases.confirmed || 0,
    cases.suspected || 0,
    cases.deaths || 0
  );
}

function getAllHistoricalData(limit = 100) {
  const stmt = db.prepare(`
    SELECT * FROM outbreak_data
    ORDER BY timestamp DESC
    LIMIT ?
  `);
  return stmt.all(limit);
}

function clearOldData(daysToKeep = 30) {
  const stmt = db.prepare(`
    DELETE FROM outbreak_data
    WHERE timestamp < datetime('now', '-' || ? || ' days')
  `);
  return stmt.run(daysToKeep);
}

module.exports = {
  db,
  initializeDatabase,
  getLatestData,
  getHistoricalData,
  getCountryData,
  insertOutbreakData,
  insertCountryData,
  getAllHistoricalData,
  clearOldData
};
