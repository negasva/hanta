const { createClient } = require('@supabase/supabase-js');

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_ANON_KEY;

console.log('[DB] Checking environment variables...');
console.log('[DB] SUPABASE_URL:', supabaseUrl ? 'SET' : 'MISSING');
console.log('[DB] SUPABASE_ANON_KEY:', supabaseKey ? 'SET' : 'MISSING');

if (!supabaseUrl || !supabaseKey) {
  console.error('[DB] ERROR: Missing SUPABASE_URL or SUPABASE_ANON_KEY environment variables');
  process.exit(1);
}

const supabase = createClient(supabaseUrl, supabaseKey);

async function initializeDatabase() {
  try {
    const { data, error } = await supabase
      .from('outbreak_data')
      .select('id')
      .limit(1);

    if (error) {
      console.error('Database check error:', error);
      throw error;
    }

    console.log('Connected to Supabase database');
  } catch (error) {
    console.error('Failed to connect to database:', error);
    throw error;
  }
}

async function getLatestData() {
  try {
    const { data, error } = await supabase
      .from('outbreak_data')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(1)
      .single();

    if (error && error.code !== 'PGRST116') {
      throw error;
    }

    return data;
  } catch (error) {
    console.error('Error getting latest data:', error);
    return null;
  }
}

async function getHistoricalData(hours = 24) {
  try {
    const cutoffDate = new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();

    const { data, error } = await supabase
      .from('outbreak_data')
      .select('*')
      .gte('created_at', cutoffDate)
      .order('created_at', { ascending: true });

    if (error) throw error;

    return data || [];
  } catch (error) {
    console.error('Error getting historical data:', error);
    return [];
  }
}

async function getCountryData() {
  try {
    const { data, error } = await supabase
      .from('country_data')
      .select('country, latitude, longitude, confirmed_cases, suspected_cases, deaths')
      .order('confirmed_cases', { ascending: false });

    if (error) throw error;

    return data || [];
  } catch (error) {
    console.error('Error getting country data:', error);
    return [];
  }
}

async function insertOutbreakData(data) {
  try {
    const { data: result, error } = await supabase
      .from('outbreak_data')
      .insert([
        {
          confirmed_cases: data.confirmed_cases || 0,
          suspected_cases: data.suspected_cases || 0,
          deaths: data.deaths || 0,
          affected_countries: data.affected_countries ? JSON.stringify(data.affected_countries) : '[]',
          source: data.source || 'unknown'
        }
      ])
      .select();

    if (error) throw error;

    return result?.[0] || { id: null };
  } catch (error) {
    console.error('Error inserting outbreak data:', error);
    throw error;
  }
}

async function insertCountryData(countryName, lat, lng, cases) {
  try {
    const { data, error } = await supabase
      .from('country_data')
      .insert([
        {
          country: countryName,
          latitude: lat,
          longitude: lng,
          confirmed_cases: cases.confirmed || 0,
          suspected_cases: cases.suspected || 0,
          deaths: cases.deaths || 0
        }
      ])
      .select();

    if (error) throw error;

    return data?.[0] || { id: null };
  } catch (error) {
    console.error('Error inserting country data:', error);
    throw error;
  }
}

async function getAllHistoricalData(limit = 100) {
  try {
    const { data, error } = await supabase
      .from('outbreak_data')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(limit);

    if (error) throw error;

    return data || [];
  } catch (error) {
    console.error('Error getting all historical data:', error);
    return [];
  }
}

async function clearOldData(daysToKeep = 30) {
  try {
    const cutoffDate = new Date(Date.now() - daysToKeep * 24 * 60 * 60 * 1000).toISOString();

    const { data: deletedOutbreak, error: error1 } = await supabase
      .from('outbreak_data')
      .delete()
      .lt('created_at', cutoffDate);

    const { data: deletedCountry, error: error2 } = await supabase
      .from('country_data')
      .delete()
      .lt('created_at', cutoffDate);

    if (error1 || error2) {
      throw error1 || error2;
    }

    return { changes: (deletedOutbreak?.length || 0) + (deletedCountry?.length || 0) };
  } catch (error) {
    console.error('Error clearing old data:', error);
    return { changes: 0 };
  }
}

module.exports = {
  supabase,
  initializeDatabase,
  getLatestData,
  getHistoricalData,
  getCountryData,
  insertOutbreakData,
  insertCountryData,
  getAllHistoricalData,
  clearOldData
};
