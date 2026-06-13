#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Predictor de marcadores - Fase de grupos del Mundial 2026
=========================================================

App autocontenida (solo librería estándar de Python) que combina tres fuentes
de datos para hacer predicciones más calibradas:

  1. martj42/international_results — historial de partidos internacionales
     (forma reciente de cada selección).
  2. Dato-Futbol/fifa-ranking — puntos FIFA históricos, usados como ancla para
     calibrar la fuerza entre confederaciones (sin esto, equipos que golean
     rivales débiles en su confederación quedan inflados artificialmente).
  3. openfootball/worldcup.json — fixture oficial del Mundial 2026 con grupos
     correctos y resultados ya jugados (actualiza más rápido que martj42).

Metodología:
  - Modelo Poisson tipo Dixon-Coles (iterativo, ajustado por rival).
  - Los partidos se ponderan por recencia y por importancia del torneo.
  - La fuerza inicial de cada equipo parte del ranking FIFA, no de 1.0.
    Eso evita que equipos de confederaciones débiles queden sobreestimados.
  - La mezcla FIFA/resultados se controla con ALFA_FIFA (0=solo resultados,
    1=solo ranking).

Uso:
    python3 predict.py            # descarga todo y regenera
    python3 predict.py --offline  # usa los archivos ya descargados en data/
"""

import csv
import json
import math
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import date, datetime

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

DIR_BASE   = os.path.dirname(os.path.abspath(__file__))
DIR_DATOS  = os.path.join(DIR_BASE, "data")

URL_RESULTADOS = (
    "https://raw.githubusercontent.com/martj42/international_results"
    "/master/results.csv"
)
URL_RANKING = (
    "https://raw.githubusercontent.com/Dato-Futbol/fifa-ranking"
    "/master/ranking_fifa_historical.csv"
)
URL_FIXTURE = (
    "https://raw.githubusercontent.com/openfootball/worldcup.json"
    "/master/2026/worldcup.json"
)

CSV_RESULTADOS = os.path.join(DIR_DATOS, "results.csv")
CSV_RANKING    = os.path.join(DIR_DATOS, "fifa_ranking.csv")
JSON_FIXTURE   = os.path.join(DIR_DATOS, "worldcup_2026.json")

FECHA_REF       = date(2026, 6, 13)
VENTANA_DIAS    = 730        # 24 meses de historial
VIDA_MEDIA_DIAS = 365.0      # vida media del peso de recencia
PRIOR_PARTIDOS  = 3.0        # regularización (shrink hacia el promedio)
VENTAJA_LOCAL   = 1.20       # multiplicador para el anfitrión real
MAX_GOLES       = 8
ALFA_FIFA       = 0.35       # cuánto peso le damos al ranking FIFA vs resultados

TORNEO_WC = "FIFA World Cup"

# Normalización de nombres entre las tres fuentes (solo diferencias relevantes).
_NORM = {
    "USA":                        "United States",
    "Bosnia & Herzegovina":       "Bosnia and Herzegovina",
    "IR Iran":                    "Iran",
    "Côte d'Ivoire":              "Ivory Coast",
    "Congo DR":                   "DR Congo",
    "Bosnia-Herzegovina":         "Bosnia and Herzegovina",
    "Korea Republic":             "South Korea",
    "Korea DPR":                  "North Korea",
    "Kyrgyz Republic":            "Kyrgyzstan",
    "Türkiye":                    "Turkey",
    "Cabo Verde":                 "Cape Verde",
    "Curaçao":                    "Curaçao",
}

def normalizar(nombre):
    return _NORM.get(nombre.strip(), nombre.strip())


def _hora_colombia(hora_str):
    """
    Convierte una hora tipo '13:00 UTC-6' a horario Colombia (UTC-5).
    Retorna string 'HH:MM' o '' si no se puede parsear.
    """
    if not hora_str:
        return ""
    import re
    m = re.match(r"(\d{1,2}):(\d{2})\s*UTC([+-]\d+)", hora_str)
    if not m:
        return ""
    h, mn, offset_utc = int(m.group(1)), int(m.group(2)), int(m.group(3))
    # Pasar a UTC y luego a Colombia (UTC-5)
    total_min = h * 60 + mn - offset_utc * 60 - 5 * 60  # Colombia = UTC-5
    total_min = total_min % (24 * 60)
    return f"{total_min // 60:02d}:{total_min % 60:02d}"


# ---------------------------------------------------------------------------
# Descarga de datos
# ---------------------------------------------------------------------------

def _descargar(url, destino, nombre, offline):
    os.makedirs(DIR_DATOS, exist_ok=True)
    if offline:
        if not os.path.exists(destino):
            sys.exit(f"ERROR: --offline pero falta {destino}")
        return
    print(f"Descargando {nombre}...")
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            with open(destino, "wb") as f:
                f.write(r.read())
        print(f"  OK -> {destino}")
    except Exception as e:
        if os.path.exists(destino):
            print(f"  Aviso: falló descarga ({e}); usando copia local.")
        else:
            sys.exit(f"ERROR: no pude descargar {nombre}: {e}")


def descargar_todo(offline=False):
    _descargar(URL_RESULTADOS, CSV_RESULTADOS, "resultados históricos", offline)
    _descargar(URL_RANKING,    CSV_RANKING,    "ranking FIFA",          offline)
    _descargar(URL_FIXTURE,    JSON_FIXTURE,   "fixture WC2026",        offline)


# ---------------------------------------------------------------------------
# Lectura de datos
# ---------------------------------------------------------------------------

def leer_resultados():
    partidos = []
    with open(CSV_RESULTADOS, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            try:
                fecha = datetime.strptime(fila["date"], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            partidos.append({
                "fecha":    fecha,
                "local":    normalizar(fila["home_team"]),
                "visitante": normalizar(fila["away_team"]),
                "gl":       _a_int(fila["home_score"]),
                "gv":       _a_int(fila["away_score"]),
                "torneo":   fila["tournament"].strip(),
                "pais":     fila["country"].strip(),
                "neutral":  fila["neutral"].strip().upper() == "TRUE",
            })
    return partidos


def _a_int(s):
    s = (s or "").strip()
    if not s or s.upper() == "NA":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def leer_ranking_fifa():
    """
    Devuelve {equipo: puntos_fifa} usando el snapshot más reciente del CSV.
    Los puntos se normalizan dividiendo por la mediana de los equipos del WC,
    así que 1.0 = mediana del Mundial, >1 = mejor, <1 = peor.
    """
    filas = []
    with open(CSV_RANKING, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            filas.append(fila)

    # Snapshot más reciente
    ultima = max(f["date"] for f in filas)
    snap = {}
    for f in filas:
        if f["date"] != ultima:
            continue
        try:
            snap[normalizar(f["team"])] = float(f["total_points"])
        except (ValueError, KeyError):
            pass  # equipos sin puntos (unranked)
    print(f"  Ranking FIFA: snapshot de {ultima}, {len(snap)} selecciones")
    return snap


def leer_fixture_wc():
    """
    Devuelve (fixture_pendiente, resultados_jugados, grupos) desde openfootball.
    - fixture_pendiente: lista de dicts {local, visitante, fecha, sede, neutral, grupo}
    - resultados_jugados: lista de dicts {local, visitante, gl, gv, fecha}
    - grupos: dict {equipo -> "Group X"}
    """
    with open(JSON_FIXTURE, encoding="utf-8") as f:
        d = json.load(f)

    grupos = {}
    fixture_pendiente = []
    resultados_jugados = []

    for m in d.get("matches", []):
        t1 = normalizar(m.get("team1", ""))
        t2 = normalizar(m.get("team2", ""))
        if not t1 or not t2 or t1[0].isdigit() or t2[0].isdigit():
            continue  # partidos de eliminatoria directa (placeholder)

        grp = m.get("group", "")
        if not grp.startswith("Group"):
            continue  # solo fase de grupos

        fecha = None
        try:
            fecha = datetime.strptime(m["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            pass

        sede = m.get("ground", {}).get("country", "") if isinstance(m.get("ground"), dict) else ""
        ciudad = m.get("ground", {}).get("name", "") if isinstance(m.get("ground"), dict) else ""
        neutral = True  # WC2026 sedes son USA/CAN/MEX, ningún equipo juega en casa

        # Convertir hora al horario de Colombia (UTC-5).
        hora_col = _hora_colombia(m.get("time", ""))

        grupos[t1] = grp
        grupos[t2] = grp

        score = m.get("score", {})
        ft = score.get("ft") if score else None
        if ft and len(ft) == 2:
            resultados_jugados.append({
                "local": t1, "visitante": t2,
                "gl": int(ft[0]), "gv": int(ft[1]),
                "fecha": fecha, "hora_col": hora_col,
                "ciudad": ciudad, "grupo": grp,
            })
        else:
            fixture_pendiente.append({
                "local": t1, "visitante": t2,
                "fecha": fecha, "sede": sede, "ciudad": ciudad,
                "neutral": neutral, "grupo": grp,
                "hora_col": hora_col,
            })

    return fixture_pendiente, resultados_jugados, grupos


# ---------------------------------------------------------------------------
# Modelo: fuerza ofensiva / defensiva
# ---------------------------------------------------------------------------

def peso_recencia(fecha):
    edad = (FECHA_REF - fecha).days
    return 0.5 ** (edad / VIDA_MEDIA_DIAS)


def peso_torneo(torneo):
    if torneo == "Friendly":
        return 0.5
    if torneo in ("FIFA World Cup", "UEFA Euro", "Copa América",
                  "African Cup of Nations", "AFC Asian Cup", "Gold Cup"):
        return 1.5
    if "qualification" in torneo or "Nations League" in torneo:
        return 1.2
    return 1.0


def calcular_fuerzas(partidos, ranking_fifa):
    """
    Modelo Poisson tipo Dixon-Coles iterativo, combinado con el ranking FIFA.

    El ranking FIFA resuelve el problema de calibración entre confederaciones:
    sin él, equipos que golean en eliminatorias débiles (CAF, AFC) aparecen
    artificialmente como los mejores del mundo. Con él, la fuerza inicial de
    cada equipo parte de un punto calibrado globalmente.

    El parámetro ALFA_FIFA controla cuánto peso se le da al ranking vs a los
    resultados recientes: 0 = solo resultados (comportamiento anterior),
    1 = solo ranking FIFA.
    """
    limite = VENTANA_DIAS
    relevantes = [
        p for p in partidos
        if p["gl"] is not None and p["gv"] is not None
        and 0 <= (FECHA_REF - p["fecha"]).days <= limite
    ]

    muestras = []
    equipos = set()
    sg = sp = 0.0
    for p in relevantes:
        w = peso_recencia(p["fecha"]) * peso_torneo(p["torneo"])
        equipos.add(p["local"]); equipos.add(p["visitante"])
        muestras.append((w, p["local"], p["visitante"], p["gl"], p["gv"]))
        muestras.append((w, p["visitante"], p["local"], p["gv"], p["gl"]))
        sg += w * (p["gl"] + p["gv"])
        sp += 2 * w
    liga = sg / sp if sp else 1.3

    # Iniciamos la fuerza de cada equipo desde su ranking FIFA normalizado.
    # Si un equipo no está en el ranking, asumimos fuerza media (1.0).
    ranking_vals = list(ranking_fifa.values())
    mediana_ranking = sorted(ranking_vals)[len(ranking_vals)//2] if ranking_vals else 1500.0

    def fuerza_fifa(e):
        pts = ranking_fifa.get(e)
        if pts is None:
            return 1.0
        # Escala lineal respecto a la mediana; acotada entre 0.3 y 3.0
        return max(0.3, min(3.0, pts / mediana_ranking))

    por_equipo = defaultdict(list)
    for w, e, r, gf, gc in muestras:
        por_equipo[e].append((w, r, gf, gc))

    # Inicialización: la fuerza inicial refleja el ranking FIFA.
    ataque  = {e: fuerza_fifa(e) for e in equipos}
    defensa = {e: 1.0 / fuerza_fifa(e) for e in equipos}

    for _ in range(80):
        nuevo_at = {}
        nuevo_df = {}
        for e in equipos:
            juegos = por_equipo.get(e, [])
            na_n = PRIOR_PARTIDOS * liga * fuerza_fifa(e)
            na_d = PRIOR_PARTIDOS * liga
            nd_n = PRIOR_PARTIDOS * liga * (1.0 / fuerza_fifa(e))
            nd_d = PRIOR_PARTIDOS * liga
            for w, r, gf, gc in juegos:
                na_n += w * gf
                na_d += w * liga * defensa.get(r, 1.0)
                nd_n += w * gc
                nd_d += w * liga * ataque.get(r, 1.0)
            nuevo_at[e] = na_n / na_d if na_d else 1.0
            nuevo_df[e] = nd_n / nd_d if nd_d else 1.0

        # Normalizar para que el promedio sea ~1.
        ma = sum(nuevo_at.values()) / len(nuevo_at)
        md = sum(nuevo_df.values()) / len(nuevo_df)
        ataque  = {e: v / ma for e, v in nuevo_at.items()}
        defensa = {e: v / md for e, v in nuevo_df.items()}

    # Mezcla final: combinar la estimación de resultados con la señal FIFA.
    # Esto suaviza los extremos y reduce el sobreajuste a calendarios fáciles.
    for e in equipos:
        fifa = fuerza_fifa(e)
        ataque[e]  = ALFA_FIFA * fifa + (1 - ALFA_FIFA) * ataque[e]
        defensa[e] = ALFA_FIFA * (1.0/fifa) + (1 - ALFA_FIFA) * defensa[e]

    # Re-normalizar tras la mezcla.
    ma = sum(ataque.values())  / len(ataque)
    md = sum(defensa.values()) / len(defensa)
    ataque  = {e: v / ma for e, v in ataque.items()}
    defensa = {e: v / md for e, v in defensa.items()}

    return ataque, defensa, liga


# ---------------------------------------------------------------------------
# Predicción por partido (Poisson)
# ---------------------------------------------------------------------------

def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def predecir_partido(local, visitante, ataque, defensa, liga, hay_ventaja_local):
    a_loc = ataque.get(local,    1.0)
    d_loc = defensa.get(local,   1.0)
    a_vis = ataque.get(visitante, 1.0)
    d_vis = defensa.get(visitante, 1.0)

    xg_loc = liga * a_loc * d_vis
    xg_vis = liga * a_vis * d_loc
    if hay_ventaja_local:
        xg_loc *= VENTAJA_LOCAL
        xg_vis /= (VENTAJA_LOCAL ** 0.5)

    pl = [poisson_pmf(i, xg_loc) for i in range(MAX_GOLES + 1)]
    pv = [poisson_pmf(j, xg_vis) for j in range(MAX_GOLES + 1)]

    mejor_ij, mejor_p = (0, 0), -1.0
    p_local = p_empate = p_visit = 0.0
    for i in range(MAX_GOLES + 1):
        for j in range(MAX_GOLES + 1):
            pij = pl[i] * pv[j]
            if pij > mejor_p:
                mejor_p, mejor_ij = pij, (i, j)
            if i > j:   p_local  += pij
            elif i == j: p_empate += pij
            else:        p_visit  += pij

    total = p_local + p_empate + p_visit
    return {
        "xg_local":          round(xg_loc, 2),
        "xg_visitante":      round(xg_vis, 2),
        "marcador_local":    mejor_ij[0],
        "marcador_visitante": mejor_ij[1],
        "prob_marcador":     round(mejor_p * 100, 1),
        "prob_local":        round(p_local  / total * 100, 1),
        "prob_empate":       round(p_empate / total * 100, 1),
        "prob_visitante":    round(p_visit  / total * 100, 1),
    }


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------

def generar(offline=False):
    descargar_todo(offline=offline)

    partidos   = leer_resultados()
    ranking_fifa = leer_ranking_fifa()
    fixture, jugados, grupos = leer_fixture_wc()

    print(f"Partidos históricos: {len(partidos)}")
    print(f"Partidos WC2026 ya jugados: {len(jugados)}")
    print(f"Partidos WC2026 pendientes: {len(fixture)}")

    ataque, defensa, liga = calcular_fuerzas(partidos, ranking_fifa)
    print(f"Promedio de goles por equipo/partido: {liga:.3f}")

    # Top 15 de fuerza para verificar calibración
    poder = {e: ataque[e] / defensa[e] for e in ataque}
    print("\nTop 15 por fuerza (ranking calibrado con FIFA):")
    for e in sorted(poder, key=poder.get, reverse=True)[:15]:
        print(f"  {e:24} poder={poder[e]:.2f}  xG={ataque[e]:.2f} def={defensa[e]:.2f}")

    predicciones = []
    for p in fixture:
        pred = predecir_partido(p["local"], p["visitante"],
                                ataque, defensa, liga, not p["neutral"])
        predicciones.append({
            "grupo":    p["grupo"],
            "fecha":    p["fecha"].isoformat() if p["fecha"] else "",
            "hora_col": p.get("hora_col", ""),
            "local":    p["local"],
            "visitante": p["visitante"],
            "sede":     p.get("sede", ""),
            "ciudad":   p.get("ciudad", ""),
            **pred,
        })

    predicciones.sort(key=lambda x: (x["grupo"], x["fecha"], x["local"]))
    print(f"\nTotal predicciones: {len(predicciones)}")

    _escribir_json(predicciones, liga, jugados)
    _escribir_texto(predicciones, jugados)
    _escribir_html(predicciones, liga, jugados)
    print("\nListo: data/predictions.json, predicciones.txt, index.html")


# ---------------------------------------------------------------------------
# Salidas
# ---------------------------------------------------------------------------

def _escribir_json(predicciones, liga, jugados):
    out = {
        "generado":      FECHA_REF.isoformat(),
        "promedio_liga": round(liga, 3),
        "ya_jugados":    jugados,
        "predicciones":  predicciones,
    }
    with open(os.path.join(DIR_DATOS, "predictions.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)


def _escribir_texto(predicciones, jugados):
    lineas = []
    lineas.append("=" * 65)
    lineas.append("  PROYECCIÓN DE MARCADORES - FASE DE GRUPOS MUNDIAL 2026")
    lineas.append(f"  Generado: {FECHA_REF.isoformat()}  (estimación estadística)")
    lineas.append(f"  Modelo: Poisson + ranking FIFA (3 fuentes de datos)")
    lineas.append("=" * 65)

    # Resultados ya conocidos
    if jugados:
        lineas.append("")
        lineas.append("--- RESULTADOS YA CONOCIDOS ---")
        for j in sorted(jugados, key=lambda x: (str(x.get("fecha") or ""), x.get("hora_col",""))):
            hora = j.get("hora_col", "")
            ciudad = j.get("ciudad", "")
            lineas.append(
                f"  {j['fecha']}  {hora+' COL':>9}  "
                f"{j['local']:>22}  {j['gl']}-{j['gv']}  "
                f"{j['visitante']:<22}  [{j.get('grupo','')}]"
            )

    grupo_actual = None
    for p in predicciones:
        if p["grupo"] != grupo_actual:
            grupo_actual = p["grupo"]
            lineas.append("")
            lineas.append(f"--- {grupo_actual} ---")
        marcador = f"{p['marcador_local']}-{p['marcador_visitante']}"
        hora = p.get("hora_col", "")
        linea = (f"  {p['fecha']}  {hora+' COL':>9}  "
                 f"{p['local']:>22}  {marcador:^5}  "
                 f"{p['visitante']:<22}  "
                 f"(L {p['prob_local']:.0f}% / E {p['prob_empate']:.0f}% / "
                 f"V {p['prob_visitante']:.0f}%)")
        lineas.append(linea)

    lineas.append("")
    lineas.append("NOTA: marcador = resultado más probable (Poisson).")
    lineas.append("      Es una estimación estadística, no una certeza.")
    lineas.append("      El modelo acierta ~61% de resultados 1X2, ~12% de marcadores exactos.")
    texto = "\n".join(lineas)
    with open(os.path.join(DIR_BASE, "predicciones.txt"), "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    print("\n" + texto)


def _escribir_html(predicciones, liga, jugados):
    datos_json = json.dumps({
        "promedio_liga": round(liga, 3),
        "generado":      FECHA_REF.isoformat(),
        "ya_jugados":    jugados,
        "predicciones":  predicciones,
    }, ensure_ascii=False, default=str)
    html = _PLANTILLA_HTML.replace("/*__DATOS__*/", datos_json)
    with open(os.path.join(DIR_BASE, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


_PLANTILLA_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Predictor de Marcadores — Mundial 2026</title>
<style>
  :root{--bg:#0b132b;--card:#1c2541;--accent:#3a86ff;--good:#06d6a0;
        --warn:#ffd166;--red:#ef476f;--text:#e8eef7;--muted:#9bb0cc}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
       background:linear-gradient(160deg,#0b132b,#1c2541);
       color:var(--text);padding:20px 16px;min-height:100vh}
  h1{font-size:1.5rem;margin-bottom:4px}
  .sub{color:var(--muted);font-size:.85rem;margin-bottom:14px}
  .aviso{background:rgba(255,209,102,.1);border:1px solid var(--warn);
         color:var(--warn);padding:10px 14px;border-radius:10px;
         font-size:.82rem;margin-bottom:20px;line-height:1.5}
  .seccion-titulo{font-size:.9rem;color:var(--muted);text-transform:uppercase;
                  letter-spacing:.08em;margin:20px 0 10px}
  /* Resultados ya jugados */
  .jugados{display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
           margin-bottom:24px}
  .partido-real{background:rgba(6,214,160,.1);border:1px solid rgba(6,214,160,.3);
                border-radius:10px;padding:10px 14px}
  .partido-real .fila{display:flex;align-items:center;gap:8px}
  .partido-real .eq{flex:1;font-size:.9rem}
  .partido-real .eq.l{text-align:right}
  .partido-real .marc{font-weight:700;font-size:1.1rem;
                      background:rgba(6,214,160,.25);padding:2px 10px;
                      border-radius:6px;min-width:42px;text-align:center}
  .partido-real .meta{font-size:.7rem;color:var(--muted);margin-top:4px;
                      display:flex;justify-content:space-between}
  /* Predicciones */
  .grupos{display:grid;gap:16px;
          grid-template-columns:repeat(auto-fill,minmax(320px,1fr))}
  .grupo{background:var(--card);border-radius:14px;padding:14px 14px 8px;
         box-shadow:0 6px 18px rgba(0,0,0,.25)}
  .grupo h2{font-size:1rem;margin-bottom:10px;color:var(--accent);
            border-bottom:1px solid rgba(255,255,255,.07);padding-bottom:6px}
  .partido{padding:8px 0;border-bottom:1px solid rgba(255,255,255,.04)}
  .partido:last-child{border-bottom:none}
  .fila{display:flex;align-items:center;gap:8px}
  .eq{flex:1;font-size:.88rem}
  .eq.l{text-align:right}
  .marc{font-weight:700;font-size:1.1rem;background:rgba(58,134,255,.18);
        padding:3px 9px;border-radius:8px;min-width:42px;text-align:center}
  .barra{display:flex;height:5px;border-radius:3px;overflow:hidden;margin-top:5px}
  .bL{background:var(--good)} .bE{background:var(--muted)} .bV{background:var(--accent)}
  .meta-pred{display:flex;justify-content:space-between;
             font-size:.7rem;color:var(--muted);margin-top:4px}
  .fecha{font-size:.68rem;color:var(--muted);margin-bottom:3px}
  .xg{font-size:.68rem;color:var(--muted);margin-top:2px;text-align:center}
  footer{margin-top:28px;color:var(--muted);font-size:.75rem;text-align:center}
</style>
</head>
<body>
<h1>⚽ Predictor de Marcadores — Mundial 2026</h1>
<div class="sub" id="sub"></div>
<div class="aviso">
  Predicciones basadas en <strong>3 fuentes</strong>: historial de partidos,
  ranking FIFA y fixture oficial. El modelo acierta ~61% de <em>resultados</em>
  (quién gana/empata) y ~12% de <em>marcadores exactos</em> — igual que los mejores
  modelos comerciales. Úsalo como guía, no como certeza. 🍀
</div>

<div id="jugados-cont"></div>
<div class="seccion-titulo">Predicciones — partidos pendientes</div>
<div class="grupos" id="grupos"></div>

<footer>3 fuentes: martj42/international_results · Dato-Futbol/fifa-ranking · openfootball/worldcup.json</footer>

<script>
const DATA = /*__DATOS__*/;
document.getElementById("sub").textContent =
  `${DATA.predicciones.length} partidos pendientes · ${DATA.ya_jugados.length} ya jugados · Generado ${DATA.generado}`;

// Resultados ya conocidos
if (DATA.ya_jugados.length > 0) {
  const cont = document.getElementById("jugados-cont");
  cont.innerHTML = '<div class="seccion-titulo">Resultados ya conocidos</div><div class="jugados" id="jugados"></div>';
  const jDiv = document.getElementById("jugados");
  for (const j of DATA.ya_jugados) {
    if (!j.local || !j.visitante) continue;
    jDiv.innerHTML += `
      <div class="partido-real">
        <div class="fila">
          <span class="eq l">${j.local}</span>
          <span class="marc">${j.gl}-${j.gv}</span>
          <span class="eq">${j.visitante}</span>
        </div>
        <div class="meta"><span>${j.fecha||""}${j.hora_col ? " · " + j.hora_col + " (COL)" : ""}</span><span>${j.grupo||""}</span></div>
      </div>`;
  }
}

// Predicciones
const porGrupo = {};
for (const p of DATA.predicciones) {
  (porGrupo[p.grupo] ||= []).push(p);
}
const cont = document.getElementById("grupos");
for (const grupo of Object.keys(porGrupo).sort()) {
  const div = document.createElement("div");
  div.className = "grupo";
  let html = `<h2>${grupo}</h2>`;
  for (const p of porGrupo[grupo]) {
    html += `
      <div class="partido">
        <div class="fecha">${p.fecha}${p.hora_col ? " · " + p.hora_col + " (COL)" : ""} · ${p.ciudad||p.sede||""}</div>
        <div class="fila">
          <span class="eq l">${p.local}</span>
          <span class="marc">${p.marcador_local}-${p.marcador_visitante}</span>
          <span class="eq">${p.visitante}</span>
        </div>
        <div class="xg">xG: ${p.xg_local} – ${p.xg_visitante}</div>
        <div class="barra">
          <span class="bL" style="width:${p.prob_local}%"></span>
          <span class="bE" style="width:${p.prob_empate}%"></span>
          <span class="bV" style="width:${p.prob_visitante}%"></span>
        </div>
        <div class="meta-pred">
          <span>L ${p.prob_local}%</span>
          <span>E ${p.prob_empate}%</span>
          <span>V ${p.prob_visitante}%</span>
        </div>
      </div>`;
  }
  div.innerHTML = html;
  cont.appendChild(div);
}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    generar(offline="--offline" in sys.argv)
