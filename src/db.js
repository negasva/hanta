const sqlite3 = require('sqlite3').verbose();
const path = require('path');

const dbPath = path.join(__dirname, '../data/hantavirus.db');
const db = new sqlite3.Database(dbPath, (err) => {
  if (err) {
    console.error('Database connection error:', err);
  } else {
    console.log('Connected to SQLite database');
    db.run('PRAGMA journal_mode = WAL');
  }
});

function initializeDatabase() {
  return new Promise((resolve, reject) => {
    const schema = `
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
    `;

    db.exec(schema, (err) => {
      if (err) reject(err);
      else resolve();
    });
  });
}

function getLatestData() {
  return new Promise((resolve, reject) => {
    db.get(
      'SELECT * FROM outbreak_data ORDER BY timestamp DESC LIMIT 1',
      (err, row) => {
        if (err) reject(err);
        else resolve(row);
      }
    );
  });
}

function getHistoricalData(hours = 24) {
  return new Promise((resolve, reject) => {
    db.all(
      `SELECT * FROM outbreak_data
       WHERE timestamp > datetime('now', '-' || ? || ' hours')
       ORDER BY timestamp ASC`,
      [hours],
      (err, rows) => {
        if (err) reject(err);
        else resolve(rows || []);
      }
    );
  });
}

function getCountryData() {
  return new Promise((resolve, reject) => {
    db.all(
      `SELECT DISTINCT
        country,
        latitude,
        longitude,
        SUM(confirmed_cases) as confirmed_cases,
        SUM(suspected_cases) as suspected_cases,
        SUM(deaths) as deaths
       FROM country_data
       WHERE timestamp = (SELECT MAX(timestamp) FROM country_data)
       GROUP BY country
       ORDER BY confirmed_cases DESC`,
      (err, rows) => {
        if (err) reject(err);
        else resolve(rows || []);
      }
    );
  });
}

function insertOutbreakData(data) {
  return new Promise((resolve, reject) => {
    db.run(
      `INSERT INTO outbreak_data (confirmed_cases, suspected_cases, deaths, affected_countries, source)
       VALUES (?, ?, ?, ?, ?)`,
      [
        data.confirmed_cases || 0,
        data.suspected_cases || 0,
        data.deaths || 0,
        JSON.stringify(data.affected_countries || []),
        data.source || 'unknown'
      ],
      function(err) {
        if (err) reject(err);
        else resolve({ id: this.lastID });
      }
    );
  });
}

function insertCountryData(countryName, lat, lng, cases) {
  return new Promise((resolve, reject) => {
    db.run(
      `INSERT INTO country_data (country, latitude, longitude, confirmed_cases, suspected_cases, deaths)
       VALUES (?, ?, ?, ?, ?, ?)`,
      [
        countryName,
        lat,
        lng,
        cases.confirmed || 0,
        cases.suspected || 0,
        cases.deaths || 0
      ],
      function(err) {
        if (err) reject(err);
        else resolve({ id: this.lastID });
      }
    );
  });
}

function getAllHistoricalData(limit = 100) {
  return new Promise((resolve, reject) => {
    db.all(
      `SELECT * FROM outbreak_data ORDER BY timestamp DESC LIMIT ?`,
      [limit],
      (err, rows) => {
        if (err) reject(err);
        else resolve(rows || []);
      }
    );
  });
}

function clearOldData(daysToKeep = 30) {
  return new Promise((resolve, reject) => {
    db.run(
      `DELETE FROM outbreak_data
       WHERE timestamp < datetime('now', '-' || ? || ' days')`,
      [daysToKeep],
      function(err) {
        if (err) reject(err);
        else resolve({ changes: this.changes });
      }
    );
  });
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
