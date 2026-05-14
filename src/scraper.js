const axios = require('axios');
const cheerio = require('cheerio');
const { insertOutbreakData, insertCountryData, db } = require('./db');

// Fallback geographic coordinates for affected countries
const countryCoordinates = {
  'Chile': { lat: -35.6751, lng: -71.5430, name: 'Chile' },
  'Argentina': { lat: -38.4161, lng: -63.6167, name: 'Argentina' },
  'Peru': { lat: -9.1900, lng: -75.0152, name: 'Peru' },
  'Colombia': { lat: 4.5709, lng: -74.2973, name: 'Colombia' },
  'Bolivia': { lat: -16.2902, lng: -63.5887, name: 'Bolivia' },
  'Ecuador': { lat: -1.8312, lng: -78.1834, name: 'Ecuador' },
  'Paraguay': { lat: -23.4425, lng: -58.4438, name: 'Paraguay' },
  'Uruguay': { lat: -32.5228, lng: -55.7658, name: 'Uruguay' },
  'Brazil': { lat: -14.2350, lng: -51.9253, name: 'Brazil' },
  'Venezuela': { lat: 6.4238, lng: -66.5897, name: 'Venezuela' }
};

async function scrapeWHO() {
  try {
    const url = 'https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON599';
    const { data } = await axios.get(url, { timeout: 10000 });
    const $ = cheerio.load(data);

    let confirmed = 0, suspected = 0, deaths = 0;

    // Extract numbers from the WHO page
    const text = $.text();
    const confirmedMatch = text.match(/confirmed.*?(\d+)/i);
    const suspectedMatch = text.match(/suspected.*?(\d+)/i);
    const deathsMatch = text.match(/deaths?.*?(\d+)/i);

    if (confirmedMatch) confirmed = parseInt(confirmedMatch[1]) || 0;
    if (suspectedMatch) suspected = parseInt(suspectedMatch[1]) || 0;
    if (deathsMatch) deaths = parseInt(deathsMatch[1]) || 0;

    return { confirmed, suspected, deaths, source: 'WHO' };
  } catch (error) {
    console.error('WHO scraping error:', error.message);
    return { confirmed: 0, suspected: 0, deaths: 0, source: 'WHO', error: true };
  }
}

async function scrapeCDC() {
  try {
    const url = 'https://www.cdc.gov/hantavirus/situation-summary/index.html';
    const { data } = await axios.get(url, { timeout: 10000 });
    const $ = cheerio.load(data);

    let confirmed = 0, suspected = 0, deaths = 0;

    const text = $.text();
    const confirmedMatch = text.match(/case.*?(\d+)/i);
    const deathsMatch = text.match(/death.*?(\d+)/i);

    if (confirmedMatch) confirmed = parseInt(confirmedMatch[1]) || 0;
    if (deathsMatch) deaths = parseInt(deathsMatch[1]) || 0;

    return { confirmed, suspected, deaths, source: 'CDC' };
  } catch (error) {
    console.error('CDC scraping error:', error.message);
    return { confirmed: 0, suspected: 0, deaths: 0, source: 'CDC', error: true };
  }
}

async function scrapeECDC() {
  try {
    const url = 'https://www.ecdc.europa.eu/en/infectious-disease-topics/hantavirus-infection/surveillance-and-updates/andes-hantavirus-outbreak';
    const { data } = await axios.get(url, { timeout: 10000 });
    const $ = cheerio.load(data);

    let confirmed = 0, suspected = 0, deaths = 0;

    const text = $.text();
    const confirmedMatch = text.match(/confirmed.*?(\d+)/i);
    const deathsMatch = text.match(/death.*?(\d+)/i);

    if (confirmedMatch) confirmed = parseInt(confirmedMatch[1]) || 0;
    if (deathsMatch) deaths = parseInt(deathsMatch[1]) || 0;

    return { confirmed, suspected, deaths, source: 'ECDC' };
  } catch (error) {
    console.error('ECDC scraping error:', error.message);
    return { confirmed: 0, suspected: 0, deaths: 0, source: 'ECDC', error: true };
  }
}

async function scrapeWikipedia() {
  try {
    const url = 'https://en.wikipedia.org/wiki/MV_Hondius_hantavirus_outbreak';
    const { data } = await axios.get(url, { timeout: 10000 });
    const $ = cheerio.load(data);

    let confirmed = 0, suspected = 0, deaths = 0;
    const affectedCountries = [];

    const text = $.text();
    const confirmedMatch = text.match(/confirmed.*?(\d+)/i);
    const deathsMatch = text.match(/death.*?(\d+)/i);

    if (confirmedMatch) confirmed = parseInt(confirmedMatch[1]) || 0;
    if (deathsMatch) deaths = parseInt(deathsMatch[1]) || 0;

    // Try to extract country names
    for (const country in countryCoordinates) {
      if (text.includes(country)) {
        affectedCountries.push(country);
      }
    }

    return { confirmed, suspected, deaths, affectedCountries, source: 'Wikipedia' };
  } catch (error) {
    console.error('Wikipedia scraping error:', error.message);
    return { confirmed: 0, suspected: 0, deaths: 0, source: 'Wikipedia', error: true };
  }
}

async function scrapeAllSources() {
  console.log(`[${new Date().toISOString()}] Starting scrape cycle...`);

  const results = await Promise.all([
    scrapeWHO(),
    scrapeCDC(),
    scrapeECDC(),
    scrapeWikipedia()
  ]);

  // Aggregate data - take highest values
  const aggregated = {
    confirmed_cases: Math.max(...results.map(r => r.confirmed || 0)),
    suspected_cases: Math.max(...results.map(r => r.suspected || 0)),
    deaths: Math.max(...results.map(r => r.deaths || 0)),
    affected_countries: [...new Set(results.flatMap(r => r.affectedCountries || []))],
    source: results.filter(r => !r.error).map(r => r.source).join(', ')
  };

  // If no affected countries found in scraping, use all as fallback
  if (aggregated.affected_countries.length === 0) {
    aggregated.affected_countries = Object.keys(countryCoordinates);
  }

  console.log('Aggregated data:', aggregated);

  // Save to database
  try {
    await insertOutbreakData(aggregated);

    // Delete old country data and insert new batch
    await new Promise((resolve, reject) => {
      const { db } = require('./db');
      db.run(
        'DELETE FROM country_data WHERE timestamp = (SELECT MAX(timestamp) FROM country_data)',
        (err) => {
          if (err) reject(err);
          else resolve();
        }
      );
    });

    for (const country of aggregated.affected_countries) {
      const coords = countryCoordinates[country];
      if (coords) {
        await insertCountryData(country, coords.lat, coords.lng, {
          confirmed: Math.floor(aggregated.confirmed_cases / aggregated.affected_countries.length),
          suspected: Math.floor(aggregated.suspected_cases / aggregated.affected_countries.length),
          deaths: Math.floor(aggregated.deaths / aggregated.affected_countries.length)
        });
      }
    }

    console.log(`[${new Date().toISOString()}] Data saved successfully`);
  } catch (error) {
    console.error('Database error:', error.message);
  }

  return aggregated;
}

// Run once if called directly
if (require.main === module) {
  const { initializeDatabase } = require('./db');
  initializeDatabase();
  scrapeAllSources().catch(console.error);
}

module.exports = { scrapeAllSources, scrapeWHO, scrapeCDC, scrapeECDC, scrapeWikipedia };
