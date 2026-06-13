# ⚽ Polla Mundial 2026 — Predictor de marcadores

App autocontenida (**solo librería estándar de Python**) que proyecta los
marcadores de la **fase de grupos del Mundial 2026** combinando **14 fuentes de
datos** y un modelo Elo + Poisson. Además del marcador, estima por partido
**tiros, tiros a puerta, córners, tarjetas y el goleador más probable**. Genera
una tabla para enviar y un tablero visual con banderas.

---

## Cómo usarlo

```bash
python3 predict.py            # descarga las fuentes y regenera todo
python3 predict.py --offline  # usa los archivos ya descargados en data/
python3 agregar_eventos.py    # (ocasional) recalcula data/event_rates.json desde StatsBomb
```

Genera:
- **`predicciones.txt`** — tabla en texto plano (horario Colombia) lista para enviar.
- **`index.html`** — tablero visual con banderas; ábrelo con doble clic.
- **`data/predictions.json`** — datos crudos.

Vuelve a correrlo a medida que se juegan partidos: las fuentes se actualizan y
los partidos restantes se recalculan solos. Un **GitHub Action diario** (12 am
hora Colombia) lo hace automáticamente.

---

## Las 14 fuentes de datos

| # | Fuente | Qué aporta |
|---|---|---|
| 1 | [martj42/international_results](https://github.com/martj42/international_results) | Historial de partidos (1872–2026) — forma reciente |
| 2 | [Dato-Futbol/fifa-ranking](https://github.com/Dato-Futbol/fifa-ranking) | Ranking FIFA histórico |
| 3 | [openfootball/worldcup.json](https://github.com/openfootball/worldcup.json) | Fixture oficial 2026, grupos A–L, horas, resultados ya jugados |
| 4 | **Elo mundial** (computado del historial) | Fuerza global calibrada y actual — **ancla principal** |
| 5 | martj42/goalscorers | Goleadores, profundidad ofensiva y % de penaltis |
| 6 | martj42/shootouts | Récord histórico en tandas de penaltis |
| 7 | martj42/former_names | Normaliza nombres a lo largo de la historia (clave para el Elo) |
| 8 | [jfjelstul/worldcup](https://github.com/jfjelstul/worldcup) `matches` | Pedigrí mundialista (partidos jugados/ganados) |
| 9 | jfjelstul/worldcup `squads` | Profundidad de plantilla mundialista |
| 10 | jfjelstul/worldcup `goals` | Tradición goleadora histórica en Mundiales |
| 11 | jfjelstul/worldcup `standings` | Posiciones en los últimos 3 Mundiales |
| 12 | [openfootball/euro.json](https://github.com/openfootball/euro.json) 2024 | Forma reciente de equipos europeos |
| 13 | [StatsBomb Open Data](https://github.com/statsbomb/open-data) | **Tasas reales por partido** de tiros, tiros a puerta, córners y tarjetas (Copa América 2024, Euro 2024, AFCON 2023, Mundial 2022) |
| 14 | jfjelstul/worldcup `bookings` | Tarjetas históricas en Mundiales (respaldo) |

Banderas: [flagcdn.com](https://flagcdn.com).

---

## Metodología

1. **Elo mundial:** se recalcula desde **todo** el historial en orden
   cronológico (fórmula *World Football Elo*: K según importancia del torneo,
   multiplicador por diferencia de goles y ventaja de local). Resuelve la
   comparación **entre confederaciones** — un equipo que golea rivales débiles
   ya no se sobreestima.
2. **Poisson tipo Dixon-Coles:** ataque y defensa por selección, ajustados de
   forma iterativa según la calidad del rival, **anclados al Elo y al ranking
   FIFA**, y ponderados por recencia (últimos 24 meses) e importancia del
   partido (amistosos pesan menos).
3. **Predicción:** con la distribución de Poisson, el **marcador más probable**
   y las probabilidades de **victoria / empate / derrota** de cada partido.
4. **Estadísticas por partido:** tiros, tiros a puerta, córners y tarjetas se
   estiman combinando la tasa **a favor** de un equipo con la tasa **en contra**
   del rival (media geométrica), ajustadas por el dominio esperado (xG) y
   **regularizadas hacia el promedio de liga** para selecciones con pocos
   partidos. El **goleador más probable** reparte el xG del equipo según la
   cuota de goles de cada jugador en los últimos 24 meses
   (`P(marca) = 1 − e^(−xG·cuota)`).

### Estadísticas por evento (StatsBomb)

Las tasas reales de tiros/córners/tarjetas se precalculan con
`agregar_eventos.py`, que descarga ~360 MB de eventos de StatsBomb y los resume
en **`data/event_rates.json`** (~18 KB, versionado en git). Así el Action diario
no descarga nada pesado: solo lee ese resumen. **38 de las 48** selecciones del
Mundial tienen datos propios; el resto usa el promedio de liga (y `bookings`
para tarjetas). Para regenerarlo: corre el workflow manual *"Recalcular
estadísticas por evento"* o `python3 agregar_eventos.py`.

### Precisión real (backtest, 710 partidos competitivos del último año)

| Métrica | Este modelo | Versión previa | Referencia |
|---|---|---|---|
| Resultado (1X2) | **63.2%** | 61.7% | "siempre gana local" ≈ 48% |
| Marcador exacto | **13.0%** | 12.1% | mejores modelos ≈ 12–15% |
| Brier (menor = mejor) | **0.467** | 0.502 | — |

**Conclusión honesta:** el modelo predice **bien quién gana**, pero el
**marcador exacto es intrínsecamente difícil** (~7 de cada 8 fallan, incluso
para las casas de apuestas). Para la polla, confía más en el favorito y las
probabilidades que en el "2-1" exacto.

### Limitaciones

- **Desfase de datos:** las fuentes se actualizan con un día o más de retraso;
  vuelve a correr `predict.py` cuando se actualicen.
- El marcador mostrado es el **modal** (más probable); por eso muchos terminan
  en marcadores bajos, que es lo correcto estadísticamente en fútbol.
- Las **estadísticas por partido** (tiros, córners, tarjetas, goleador) son
  **promedios esperados**, no predicciones exactas. Reflejan el estilo histórico
  reciente de cada selección, no el desarrollo concreto de un partido.

### Parámetros ajustables (arriba en `predict.py`)

| Parámetro | Significado | Valor |
|---|---|---|
| `VENTANA_DIAS` | Historial para el modelo de goles | 730 |
| `ALFA_ANCLA` | Mezcla fuerza-ancla (Elo+FIFA) vs goles | 0.45 |
| `VENTAJA_LOCAL` | Multiplicador del anfitrión | 1.18 |
| `ELO_HFA` | Ventaja de local en puntos Elo | 70 |
| `PRIOR_EVENTOS` | Regularización de tasas por evento hacia la liga | 4.0 |

---

## ⚠️ Aviso

Es una **estimación estadística**, no una certeza. Úsala como guía divertida
para la polla. 🍀
