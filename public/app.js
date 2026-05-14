// Global variables
let map;
let markers = {};
let chart;
let lastUpdate = null;
let nextUpdateTime = null;

console.log('App.js loaded');
console.log('Leaflet available:', typeof L !== 'undefined');
console.log('Chart available:', typeof Chart !== 'undefined');

// Initialize the application
async function init() {
  try {
    console.log('Init starting...');
    // Initialize map
    console.log('Initializing map...');
    initializeMap();
    console.log('Map initialized successfully');

    // Load initial data
    await loadData();

    // Start auto-refresh (every 15 minutes)
    setInterval(loadData, 15 * 60 * 1000);

    // Update countdown timer
    setInterval(updateNextUpdateTime, 1000);

    // Initial countdown update
    updateNextUpdateTime();

    console.log('Application initialized successfully');
  } catch (error) {
    console.error('Initialization error:', error);
    setStatus('error');
  }
}

// Initialize Leaflet map
function initializeMap() {
  map = L.map('map').setView([-15, -65], 4);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors',
    maxZoom: 19,
    minZoom: 2,
    className: 'map-tile'
  }).addTo(map);

  // Custom tile layer styling for dark mode
  const style = document.createElement('style');
  style.textContent = `
    .leaflet-tile {
      filter: invert(0.93) hue-rotate(200deg);
    }
  `;
  document.head.appendChild(style);
}

// Load data from API
async function loadData() {
  try {
    setStatus('loading');

    const [casosRes, paisesRes, historialRes] = await Promise.all([
      fetch('/api/casos'),
      fetch('/api/paises'),
      fetch('/api/all-history')
    ]);

    if (!casosRes.ok) {
      throw new Error(`/api/casos failed: ${casosRes.status}`);
    }
    if (!paisesRes.ok) {
      throw new Error(`/api/paises failed: ${paisesRes.status}`);
    }
    if (!historialRes.ok) {
      throw new Error(`/api/all-history failed: ${historialRes.status}`);
    }

    const casosData = await casosRes.json();
    const paisesData = await paisesRes.json();
    const historialData = await historialRes.json();

    console.log('Loaded casos:', casosData);
    console.log('Loaded paises:', paisesData);
    console.log('Loaded historial:', historialData);

    // Update sidebar statistics
    if (casosData) {
      updateStatistics(casosData);
    }

    // Update map with country data
    if (paisesData && paisesData.length > 0) {
      updateMap(paisesData);
    } else {
      console.warn('No paises data available');
    }

    // Update chart
    if (historialData && historialData.length > 0) {
      updateChart(historialData);
    } else {
      console.warn('No historial data available');
    }

    // Update countries list
    if (paisesData && paisesData.length > 0) {
      updateCountriesList(paisesData);
    }

    // Update last update time
    if (casosData && casosData.timestamp) {
      lastUpdate = new Date(casosData.timestamp);
      updateLastUpdateTime();
    }

    setStatus('ok');
  } catch (error) {
    console.error('Data loading error:', error);
    console.error('Stack:', error.stack);
    setStatus('error');
  }
}

// Update statistics in sidebar
function updateStatistics(data) {
  document.getElementById('stat-confirmed').textContent = data.confirmed_cases.toLocaleString();
  document.getElementById('stat-suspected').textContent = data.suspected_cases.toLocaleString();
  document.getElementById('stat-deaths').textContent = data.deaths.toLocaleString();
  document.getElementById('stat-countries').textContent = (data.affected_countries || []).length;
}

// Update map markers
function updateMap(countriesData) {
  // Clear existing markers
  Object.values(markers).forEach(marker => map.removeLayer(marker));
  markers = {};

  // Add new markers
  countriesData.forEach(country => {
    const icon = L.divIcon({
      className: 'custom-marker',
      html: `
        <div class="marker-content">
          <div class="marker-count">${country.confirmed_cases}</div>
        </div>
      `,
      iconSize: [40, 40],
      iconAnchor: [20, 20],
      popupAnchor: [0, -20]
    });

    const marker = L.marker([country.latitude, country.longitude], { icon }).addTo(map);

    const popupContent = `
      <div class="country-popup">
        <h4>${country.country}</h4>
        <p><strong>Confirmados:</strong> ${country.confirmed_cases}</p>
        <p><strong>Sospechosos:</strong> ${country.suspected_cases}</p>
        <p><strong>Muertes:</strong> ${country.deaths}</p>
      </div>
    `;

    marker.bindPopup(popupContent);
    markers[country.country] = marker;
  });

  // Inject custom marker styles
  const styleEl = document.querySelector('style[data-markers]') || document.createElement('style');
  styleEl.setAttribute('data-markers', 'true');
  styleEl.textContent = `
    .custom-marker .marker-content {
      background: linear-gradient(135deg, #ff6b6b 0%, #ffa500 100%);
      border: 2px solid #ffd700;
      border-radius: 50%;
      width: 100%;
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 0 12px rgba(255, 107, 107, 0.6);
      font-weight: bold;
      color: white;
      font-size: 12px;
    }

    .custom-marker .marker-count {
      text-shadow: 0 0 4px rgba(0, 0, 0, 0.8);
    }

    .country-popup h4 {
      margin-bottom: 8px;
      color: #e6edf3;
    }

    .country-popup p {
      margin: 4px 0;
      color: #8b949e;
    }

    .country-popup strong {
      color: #e6edf3;
    }
  `;
  if (!document.head.querySelector('style[data-markers]')) {
    document.head.appendChild(styleEl);
  }
}

// Update evolution chart
function updateChart(historialData) {
  const ctx = document.getElementById('evolutionChart').getContext('2d');

  const timestamps = historialData.map(d => {
    const date = new Date(d.timestamp);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit'
    });
  });

  const confirmedData = historialData.map(d => d.confirmed_cases);
  const suspectedData = historialData.map(d => d.suspected_cases);
  const deathsData = historialData.map(d => d.deaths);

  if (chart) {
    chart.data.labels = timestamps;
    chart.data.datasets[0].data = confirmedData;
    chart.data.datasets[1].data = suspectedData;
    chart.data.datasets[2].data = deathsData;
    chart.update();
  } else {
    chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: timestamps,
        datasets: [
          {
            label: 'Casos Confirmados',
            data: confirmedData,
            borderColor: '#3fb950',
            backgroundColor: 'rgba(63, 185, 80, 0.1)',
            borderWidth: 2,
            fill: true,
            tension: 0.4,
            pointRadius: 4,
            pointHoverRadius: 6,
            pointBackgroundColor: '#3fb950',
            pointBorderColor: '#fff'
          },
          {
            label: 'Casos Sospechosos',
            data: suspectedData,
            borderColor: '#d29922',
            backgroundColor: 'rgba(210, 153, 34, 0.1)',
            borderWidth: 2,
            fill: true,
            tension: 0.4,
            pointRadius: 4,
            pointHoverRadius: 6,
            pointBackgroundColor: '#d29922',
            pointBorderColor: '#fff'
          },
          {
            label: 'Muertes',
            data: deathsData,
            borderColor: '#f85149',
            backgroundColor: 'rgba(248, 81, 73, 0.1)',
            borderWidth: 2,
            fill: true,
            tension: 0.4,
            pointRadius: 4,
            pointHoverRadius: 6,
            pointBackgroundColor: '#f85149',
            pointBorderColor: '#fff'
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            labels: {
              color: '#8b949e',
              font: {
                size: 12
              },
              padding: 15,
              usePointStyle: true
            },
            align: 'end'
          },
          tooltip: {
            backgroundColor: 'rgba(13, 17, 23, 0.9)',
            titleColor: '#e6edf3',
            bodyColor: '#8b949e',
            borderColor: '#30363d',
            borderWidth: 1,
            padding: 12,
            displayColors: true,
            callbacks: {
              title: (context) => {
                return 'Fecha: ' + context[0].label;
              },
              label: (context) => {
                return context.dataset.label + ': ' + context.parsed.y.toLocaleString();
              }
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: {
              color: '#30363d'
            },
            ticks: {
              color: '#8b949e'
            }
          },
          x: {
            grid: {
              color: '#30363d'
            },
            ticks: {
              color: '#8b949e',
              maxRotation: 45,
              minRotation: 0
            }
          }
        }
      }
    });
  }
}

// Update countries list in sidebar
function updateCountriesList(countriesData) {
  const list = document.getElementById('countries-list');
  list.innerHTML = countriesData
    .sort((a, b) => b.confirmed_cases - a.confirmed_cases)
    .map(country => `<li>${country.country} (${country.confirmed_cases})</li>`)
    .join('');
}

// Update last update time
function updateLastUpdateTime() {
  if (lastUpdate) {
    const timeStr = lastUpdate.toLocaleString('es-ES', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
    document.getElementById('last-update').textContent = timeStr;
  }
}

// Update next update time countdown
function updateNextUpdateTime() {
  if (!lastUpdate) return;

  // Next update is 15 minutes after last update
  const now = new Date();
  nextUpdateTime = new Date(lastUpdate.getTime() + 15 * 60 * 1000);

  const diff = nextUpdateTime - now;

  if (diff <= 0) {
    document.getElementById('next-update').textContent = 'Pronto...';
    return;
  }

  const minutes = Math.floor(diff / 60000);
  const seconds = Math.floor((diff % 60000) / 1000);

  document.getElementById('next-update').textContent = `${minutes}m ${seconds}s`;
}

// Set status indicator
function setStatus(status) {
  const statusEl = document.getElementById('status');
  statusEl.className = 'value status ' + status;

  const statusTexts = {
    'ok': 'En línea',
    'loading': 'Actualizando...',
    'error': 'Error'
  };

  statusEl.textContent = statusTexts[status] || 'Desconocido';
}

// Start the application when DOM is ready
console.log('Document readyState:', document.readyState);
if (document.readyState === 'loading') {
  console.log('Waiting for DOMContentLoaded...');
  document.addEventListener('DOMContentLoaded', () => {
    console.log('DOMContentLoaded fired');
    init();
  });
} else {
  console.log('DOM already loaded, calling init immediately');
  init();
}
