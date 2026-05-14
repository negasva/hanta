# Hantavirus Andes Monitoring Application

Aplicación web completa para monitorear el brote de hantavirus Andes (MV Hondius, 2026) con datos en tiempo real desde múltiples fuentes internacionales.

## Características

### Backend (Node.js + Express)
- **Web Scraping Automático**: Extrae datos cada hora desde:
  - WHO (World Health Organization)
  - CDC (Centers for Disease Control and Prevention)
  - ECDC (European Centre for Disease Prevention and Control)
  - Wikipedia
  
- **Base de Datos SQLite**: Almacenamiento persistente con historial timestamped
- **API REST** con endpoints para datos actuales, históricos y por país
- **Programación Automática**: Scraping cada hora y limpieza de datos cada día

### Frontend (HTML/CSS/JS)
- **Mapa Interactivo**: Leaflet.js + OpenStreetMap con marcadores por país
- **Panel de Estadísticas**: Casos confirmados, sospechosos, muertes y países afectados
- **Gráfico de Evolución Temporal**: Chart.js con datos históricos
- **Diseño Oscuro Moderno**: Responsive y optimizado para todos los dispositivos
- **Auto-actualización**: Refresco cada 60 minutos sin necesidad de recargar la página

## Requisitos Previos

- Node.js >= 16.0.0
- npm (incluido con Node.js)
- Git

## Instalación

### 1. Clonar el Repositorio
```bash
git clone <repository-url>
cd hanta
```

### 2. Instalar Dependencias
```bash
npm install
```

### 3. Crear Estructura de Datos
```bash
mkdir -p data
```

### 4. (Opcional) Configurar Variables de Entorno
```bash
cp .env.example .env
```

No se requieren variables de entorno para funcionamiento básico.

## Uso

### Iniciar la Aplicación
```bash
npm start
```

La aplicación estará disponible en `http://localhost:3000`

### Ejecutar Scraper Manual
```bash
npm run scrape
```

## Estructura del Proyecto

```
hanta/
├── src/
│   ├── server.js        # Servidor Express y configuración de rutas
│   ├── scraper.js       # Lógica de web scraping
│   └── db.js            # Operaciones de base de datos SQLite
├── public/
│   ├── index.html       # Interfaz principal
│   ├── style.css        # Estilos (tema oscuro)
│   └── app.js           # Lógica del frontend
├── data/
│   └── hantavirus.db    # Base de datos SQLite (se crea automáticamente)
├── package.json         # Dependencias y scripts
├── README.md            # Este archivo
└── .gitignore           # Archivos ignorados por git
```

## API Endpoints

### GET `/api/casos`
Obtiene los datos más recientes de casos, muertes y países afectados.

**Respuesta:**
```json
{
  "timestamp": "2026-05-14T10:30:00.000Z",
  "confirmed_cases": 450,
  "suspected_cases": 120,
  "deaths": 85,
  "affected_countries": ["Chile", "Argentina", "Peru"],
  "source": "WHO, CDC, ECDC"
}
```

### GET `/api/historial?hours=24`
Obtiene datos históricos de los últimos N horas (default: 24 horas).

**Respuesta:**
```json
[
  {
    "timestamp": "2026-05-14T10:00:00.000Z",
    "confirmed_cases": 450,
    "suspected_cases": 120,
    "deaths": 85
  },
  ...
]
```

### GET `/api/paises`
Obtiene lista de países afectados con coordenadas geográficas y estadísticas.

**Respuesta:**
```json
[
  {
    "country": "Chile",
    "latitude": -35.6751,
    "longitude": -71.5430,
    "confirmed_cases": 200,
    "suspected_cases": 50,
    "deaths": 40
  },
  ...
]
```

### GET `/api/all-history?limit=100`
Obtiene todos los registros históricos (máximo especificado, default: 100).

### POST `/api/scrape`
Dispara un scraping manual (útil para testing).

### GET `/api/health`
Verifica que el servidor está funcionando.

## Funcionalidades Técnicas

### Scraping de Múltiples Fuentes
La aplicación scrappea 4 fuentes internacionales diferentes y:
- Extrae números de casos confirmados, sospechosos y muertes
- Identifica países afectados
- Usa coordenadas geográficas hardcodeadas como fallback
- Continúa operando incluso si una fuente falla

### Programación Automática
- **Scraping**: Cada hora (0:00 de cada hora UTC)
- **Limpieza de datos**: Cada medianoche (conserva últimos 30 días)

### Manejo de Errores
- Si una fuente de scraping falla, continúa con las demás
- Los errores se registran en la consola para debugging
- La aplicación mantiene funcionalidad incluso con fallos parciales

### Base de Datos
- SQLite con WAL (Write-Ahead Logging) para mejor concurrencia
- Índices en timestamps para consultas rápidas
- Datos históricos con timestamp automático

## Diseño Responsive

La aplicación se adapta automáticamente a:
- **Desktop**: Sidebar lateral con 320px + contenido principal
- **Tablets**: Sidebar colapsable, mapa optimizado
- **Móviles**: Interfaz apilada verticalmente, controles optimizados

## Tecnologías Utilizadas

### Backend
- **Express.js**: Framework web minimalista
- **Axios**: Cliente HTTP para web scraping
- **Cheerio**: Parser HTML/XML type jQuery
- **better-sqlite3**: Base de datos SQLite rápida y sincrónica
- **node-cron**: Programador de tareas
- **CORS**: Manejo de solicitudes de origen cruzado

### Frontend
- **Leaflet.js**: Librería de mapas interactivos
- **Chart.js**: Gráficos y visualización de datos
- **OpenStreetMap**: Tiles de mapas gratuitos
- **CSS3**: Diseño moderno con variables CSS

## Configuración de Puertos

- **Puerto predeterminado**: 3000
- **Puerto personalizado**: `PORT=8080 npm start`

## Limpieza de Datos Antigua

La aplicación automáticamente elimina datos más antiguos que 30 días cada medianoche. Para ajustar este período, edita `src/server.js`:

```javascript
clearOldData(30); // cambiar 30 por el número de días deseado
```

## Troubleshooting

### Puerto 3000 en uso
```bash
PORT=8080 npm start
```

### Error de base de datos
```bash
rm data/hantavirus.db
npm start
```

### Problemas de CORS
Asegúrate de que el frontend se está sirviendo desde el mismo servidor.

### Scraping no funciona
- Verifica conexión a internet
- Verifica que las URLs están actualizadas
- Revisa la consola para errores específicos

## Licencia

MIT

## Contribuciones

Las contribuciones son bienvenidas. Por favor, crea un pull request con tus cambios.

## Contacto y Soporte

Para reportar problemas o sugerencias, abre un issue en el repositorio.

---

**Nota Importante**: Esta aplicación está diseñada con propósitos educativos y de monitoreo de salud pública. Los datos se obtienen de fuentes públicas confiables.