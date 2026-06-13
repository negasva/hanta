# ⚽ Predictor de Marcadores — Mundial 2026

App sencilla y autocontenida para proyectar los marcadores de la **fase de
grupos del Mundial 2026**, pensada para una polla de oficina.

No usa dependencias externas: **solo la librería estándar de Python 3**.

---

## Cómo usarlo

```bash
python3 predict.py
```

Esto:

1. Descarga el dataset abierto de resultados internacionales.
2. Extrae el fixture oficial del Mundial 2026 y reconstruye los 12 grupos
   automáticamente.
3. Calcula la fuerza de cada selección y predice cada partido.
4. Genera tres salidas:
   - **`predicciones.txt`** → tabla en texto plano, lista para copiar y enviar.
   - **`index.html`** → tablero visual; ábrelo con doble clic (datos embebidos,
     no necesita servidor ni internet).
   - **`data/predictions.json`** → datos crudos por si quieres reusarlos.

Para volver a generar sin descargar de nuevo (usa la copia ya bajada):

```bash
python3 predict.py --offline
```

Vuelve a correrlo a medida que se juegan partidos: el dataset se actualiza y
las predicciones de los partidos restantes se recalculan solas.

---

## Metodología

El modelo es un **Poisson tipo Dixon-Coles simplificado**:

1. **Ventana de datos:** solo partidos de los **últimos 24 meses** de cada
   selección.
2. **Recencia:** cada partido se pondera con decaimiento exponencial
   (vida media de 1 año), así que los resultados recientes pesan más.
3. **Importancia del partido:** un amistoso predice peor que un partido oficial,
   así que pesa menos (0.5); los torneos grandes y eliminatorias pesan más
   (1.2–1.5). Validado por backtest (ver abajo).
4. **Fuerza ofensiva y defensiva:** se ajustan de forma **iterativa teniendo en
   cuenta la calidad del rival** (golear a un equipo flojo vale menos que
   golearle a uno fuerte). Los equipos con pocos partidos se regularizan hacia
   el promedio.
5. **Goles esperados (xG):** para cada partido se combinan el ataque de un
   equipo y la defensa del otro, con una **ventaja de localía** aplicada solo al
   anfitrión real (partidos no neutrales).
6. **Marcador y probabilidades:** con la distribución de Poisson se calcula el
   **marcador más probable** y las probabilidades de **victoria / empate /
   derrota**.

### Precisión real (backtest sobre el último año, 708 partidos competitivos)

| Métrica | Modelo | Referencia |
|---|---|---|
| Acierto de **resultado** (gana/empata/pierde) | **~61%** | "siempre gana local" ≈ 48% |
| Acierto de **marcador exacto** | **~12–13%** | techo de los mejores modelos ≈ 12–15% |

**Conclusión honesta:** el modelo predice **bien quién gana** (mejor que cualquier
regla simple), pero el **marcador exacto es intrínsecamente difícil**: ~7 de cada
8 fallan, y eso le pasa hasta a las casas de apuestas. Para la polla, confía más
en el favorito y las probabilidades que en el "2-1" exacto.

### Limitaciones conocidas

- **Desfase de datos:** la fuente se actualiza con un día (o más) de retraso, así
  que los últimos partidos jugados pueden no estar todavía cargados. Vuelve a
  correr `predict.py` cuando la fuente se actualice.
- **Conectividad entre confederaciones:** las selecciones de África, Asia, etc.
  apenas juegan contra las de Europa/Sudamérica, así que sus fuerzas pueden
  quedar **infladas o desinfladas** (p. ej. un equipo que golea en su
  eliminatoria continental). Sin un rating externo no se puede corregir del todo.

### Parámetros ajustables (arriba en `predict.py`)

| Parámetro | Significado | Valor |
|---|---|---|
| `VENTANA_DIAS` | Historial considerado | 730 (24 meses) |
| `VIDA_MEDIA_DIAS` | Vida media del peso por recencia | 365 |
| `PRIOR_PARTIDOS` | Regularización para equipos con pocos datos | 4 |
| `VENTAJA_LOCAL` | Multiplicador de goles del anfitrión | 1.25 |
| `peso_torneo()` | Peso por importancia (amistoso 0.5 … torneo 1.5) | función |
| `FECHA_REF` | Fecha de referencia ("hoy") | 2026-06-13 |

---

## ⚠️ Aviso

Esto es una **estimación estadística** basada en la forma reciente, **no una
certeza**. Ningún modelo acierta marcadores exactos de forma fiable; lo más
robusto son los favoritos y las probabilidades, no el resultado exacto.
Úsalo como guía divertida para la polla. 🍀

## Fuente de datos

[`martj42/international_results`](https://github.com/martj42/international_results)
— resultados de partidos internacionales desde 1872, dominio público.
