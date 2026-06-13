#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Predictor de marcadores — Fase de grupos del Mundial 2026
=========================================================

App autocontenida (solo librería estándar de Python) que combina 8 fuentes de
datos para producir predicciones calibradas y un tablero visual con banderas.

FUENTES DE DATOS (14)
---------------------
Base (7):
  1. martj42/international_results .......... historial de partidos (1872–2026)
  2. Dato-Futbol/fifa-ranking ............... ranking FIFA histórico
  3. openfootball/worldcup.json 2026 ........ fixture oficial, grupos, horas, resultados
  4. ELO mundial (computado del historial) .. fuerza global calibrada — ancla principal
  5. martj42/goalscorers.csv ................ goleadores, profundidad, % penaltis
  6. martj42/shootouts.csv .................. récord en tandas de penaltis
  7. martj42/former_names.csv ............... normaliza nombres (clave para el Elo)

Fuerza del modelo (5):
  8. jfjelstul/worldcup/matches.csv ......... pedigrí mundialista (partidos/triunfos)
  9. jfjelstul/worldcup/squads.csv .......... profundidad de plantilla mundialista
 10. jfjelstul/worldcup/goals.csv ........... tradición goleadora histórica en WCs
 11. jfjelstul/worldcup/standings.csv ....... posiciones en últimos 3 Mundiales
 12. openfootball/euro.json 2024 ............ forma reciente equipos europeos

Estadísticas por partido (2):
 13. StatsBomb Open Data ................... tasas reales de tiros, tiros a puerta,
                                             córners y tarjetas por selección
                                             (Copa América 2024, Euro 2024, AFCON
                                             2023, Mundial 2022). Precalculado por
                                             agregar_eventos.py -> data/event_rates.json
 14. jfjelstul/worldcup/bookings.csv ....... tarjetas históricas en Mundiales
                                             (respaldo para selecciones sin StatsBomb)

MODELO
------
  - ELO: se recalcula desde todo el historial (fórmula World Football Elo, con
    K por importancia del torneo, diferencia de goles y ventaja de local).
    Es el ancla principal de fuerza: resuelve la comparación entre
    confederaciones (un equipo que golea rivales débiles no se sobreestima).
  - Poisson tipo Dixon-Coles: ataque/defensa iterativos ajustados por rival,
    anclados al Elo y al ranking FIFA, ponderados por recencia e importancia.
  - Predicción por partido: marcador más probable + probabilidades 1X2 + xG.
  - Estadísticas por partido: tiros, tiros a puerta, córners, tarjetas y goleador
    probable, combinando la tasa 'a favor' de un equipo con la 'en contra' del
    rival (media geométrica), regularizadas hacia el promedio de liga.

Uso:
    python3 predict.py            # descarga todo y regenera
    python3 predict.py --offline  # usa los archivos ya descargados en data/
    python3 agregar_eventos.py    # (ocasional) recalcula event_rates.json desde StatsBomb
"""

import csv
import json
import math
import os
import sys
import urllib.request
from collections import defaultdict, Counter
from datetime import date, datetime

# ===========================================================================
# Configuración
# ===========================================================================

DIR_BASE  = os.path.dirname(os.path.abspath(__file__))
DIR_DATOS = os.path.join(DIR_BASE, "data")

FUENTES = {
    # Base (7 fuentes originales)
    "resultados":    ("https://raw.githubusercontent.com/martj42/international_results/master/results.csv",      "results.csv"),
    "ranking":       ("https://raw.githubusercontent.com/Dato-Futbol/fifa-ranking/master/ranking_fifa_historical.csv", "fifa_ranking.csv"),
    "fixture":       ("https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json",  "worldcup_2026.json"),
    "goleadores":    ("https://raw.githubusercontent.com/martj42/international_results/master/goalscorers.csv",   "goalscorers.csv"),
    "tandas":        ("https://raw.githubusercontent.com/martj42/international_results/master/shootouts.csv",     "shootouts.csv"),
    "exnombres":     ("https://raw.githubusercontent.com/martj42/international_results/master/former_names.csv",  "former_names.csv"),
    "mundiales":     ("https://raw.githubusercontent.com/jfjelstul/worldcup/master/data-csv/matches.csv",        "wc_history.csv"),
    # 5 fuentes nuevas
    "plantillas_wc": ("https://raw.githubusercontent.com/jfjelstul/worldcup/master/data-csv/squads.csv",         "wc_squads.csv"),
    "wc2022":        ("https://raw.githubusercontent.com/openfootball/worldcup.json/master/2022/worldcup.json",  "worldcup_2022.json"),
    "goles_wc":      ("https://raw.githubusercontent.com/jfjelstul/worldcup/master/data-csv/goals.csv",          "wc_goals.csv"),
    "posiciones_wc": ("https://raw.githubusercontent.com/jfjelstul/worldcup/master/data-csv/tournament_standings.csv", "wc_standings.csv"),
    "euro2024":      ("https://raw.githubusercontent.com/openfootball/euro.json/master/2024/euro.json",          "euro_2024.json"),
    # Estadísticas por evento: tarjetas históricas de Mundiales (jfjelstul/bookings).
    # Las tasas de tiros/córners/tarjetas vienen de data/event_rates.json (StatsBomb),
    # precalculado por agregar_eventos.py y versionado en git (no se descarga aquí).
    "tarjetas_wc":   ("https://raw.githubusercontent.com/jfjelstul/worldcup/master/data-csv/bookings.csv",       "wc_bookings.csv"),
}

FECHA_REF       = date(2026, 6, 13)
VENTANA_DIAS    = 730        # 24 meses para el modelo de goles
VIDA_MEDIA_DIAS = 365.0      # vida media del peso de recencia
PRIOR_PARTIDOS  = 3.0        # regularización del modelo de goles
VENTAJA_LOCAL   = 1.18       # multiplicador de goles para el anfitrión real
MAX_GOLES       = 8
ALFA_ANCLA      = 0.45       # mezcla: fuerza ancla (Elo+FIFA) vs ajuste de goles

# Elo
ELO_INICIAL = 1500.0
ELO_HFA     = 70.0           # ventaja de local en puntos Elo

# Normalización de nombres entre fuentes
_NORM = {
    "USA": "United States", "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina", "IR Iran": "Iran",
    "Côte d'Ivoire": "Ivory Coast", "Congo DR": "DR Congo",
    "Korea Republic": "South Korea", "Korea DPR": "North Korea",
    "Kyrgyz Republic": "Kyrgyzstan", "Türkiye": "Turkey", "Cabo Verde": "Cape Verde",
    "China PR": "China", "Chinese Taipei": "Taiwan",
}

# Código de bandera (flagcdn.com) por selección clasificada
_BANDERA = {
    "Mexico": "mx", "South Korea": "kr", "Czech Republic": "cz", "South Africa": "za",
    "Canada": "ca", "Switzerland": "ch", "Qatar": "qa", "Bosnia and Herzegovina": "ba",
    "Brazil": "br", "Morocco": "ma", "Scotland": "gb-sct", "Haiti": "ht",
    "United States": "us", "Paraguay": "py", "Australia": "au", "Turkey": "tr",
    "Germany": "de", "Curaçao": "cw", "Ecuador": "ec", "Ivory Coast": "ci",
    "Netherlands": "nl", "Japan": "jp", "Sweden": "se", "Tunisia": "tn",
    "Belgium": "be", "Egypt": "eg", "Iran": "ir", "New Zealand": "nz",
    "Spain": "es", "Cape Verde": "cv", "Saudi Arabia": "sa", "Uruguay": "uy",
    "France": "fr", "Senegal": "sn", "Iraq": "iq", "Norway": "no",
    "Argentina": "ar", "Algeria": "dz", "Austria": "at", "Jordan": "jo",
    "Colombia": "co", "Portugal": "pt", "DR Congo": "cd", "Uzbekistan": "uz",
    "England": "gb-eng", "Croatia": "hr", "Ghana": "gh", "Panama": "pa",
}

_EXNOMBRES = {}  # se llena al leer former_names.csv


def normalizar(nombre):
    n = (nombre or "").strip()
    n = _NORM.get(n, n)
    return _EXNOMBRES.get(n, n)


def bandera(equipo):
    return _BANDERA.get(equipo, "")


def hora_colombia(hora_str):
    """'13:00 UTC-6' -> 'HH:MM' en horario Colombia (UTC-5)."""
    if not hora_str:
        return ""
    import re
    m = re.match(r"(\d{1,2}):(\d{2})\s*UTC([+-]\d+)", hora_str)
    if not m:
        return ""
    h, mn, off = int(m.group(1)), int(m.group(2)), int(m.group(3))
    t = (h * 60 + mn - off * 60 - 5 * 60) % (24 * 60)
    return f"{t // 60:02d}:{t % 60:02d}"


# ===========================================================================
# Descarga
# ===========================================================================

def descargar_todo(offline=False):
    os.makedirs(DIR_DATOS, exist_ok=True)
    for nombre, (url, archivo) in FUENTES.items():
        destino = os.path.join(DIR_DATOS, archivo)
        if offline:
            if not os.path.exists(destino):
                print(f"  Aviso: falta {archivo} (--offline), se omite {nombre}")
            continue
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                with open(destino, "wb") as f:
                    f.write(r.read())
            print(f"  OK  {nombre:12} -> {archivo}")
        except Exception as e:
            if os.path.exists(destino):
                print(f"  Aviso: falló {nombre} ({e}); uso copia local.")
            else:
                print(f"  ERROR: sin {nombre} y sin copia local ({e})")


def _ruta(nombre):
    return os.path.join(DIR_DATOS, FUENTES[nombre][1])


# ===========================================================================
# Lectura de fuentes
# ===========================================================================

def cargar_exnombres():
    """former_names.csv -> mapea nombre antiguo a nombre actual (mejora el Elo)."""
    ruta = _ruta("exnombres")
    if not os.path.exists(ruta):
        return
    with open(ruta, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            ant, act = fila.get("former", "").strip(), fila.get("current", "").strip()
            if ant and act:
                _EXNOMBRES[ant] = act


def _a_int(s):
    s = (s or "").strip()
    if not s or s.upper() == "NA":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def leer_resultados():
    partidos = []
    with open(_ruta("resultados"), newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            try:
                fecha = datetime.strptime(fila["date"], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            partidos.append({
                "fecha": fecha,
                "local": normalizar(fila["home_team"]),
                "visitante": normalizar(fila["away_team"]),
                "gl": _a_int(fila["home_score"]),
                "gv": _a_int(fila["away_score"]),
                "torneo": fila["tournament"].strip(),
                "neutral": fila["neutral"].strip().upper() == "TRUE",
            })
    partidos.sort(key=lambda p: p["fecha"])
    return partidos


def leer_ranking_fifa():
    filas = []
    with open(_ruta("ranking"), newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    ultima = max(f["date"] for f in filas)
    snap = {}
    for f in filas:
        if f["date"] != ultima:
            continue
        try:
            snap[normalizar(f["team"])] = float(f["total_points"])
        except (ValueError, KeyError):
            pass
    return snap


def leer_fixture_wc():
    with open(_ruta("fixture"), encoding="utf-8") as f:
        d = json.load(f)
    grupos, fixture, jugados = {}, [], []
    for m in d.get("matches", []):
        t1, t2 = normalizar(m.get("team1", "")), normalizar(m.get("team2", ""))
        if not t1 or not t2 or t1[0].isdigit() or t2[0].isdigit():
            continue
        grp = m.get("group", "")
        if not grp.startswith("Group"):
            continue
        try:
            fecha = datetime.strptime(m["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            fecha = None
        ciudad = m.get("ground", {}).get("name", "") if isinstance(m.get("ground"), dict) else ""
        hora = hora_colombia(m.get("time", ""))
        grupos[t1] = grp; grupos[t2] = grp
        ft = (m.get("score") or {}).get("ft")
        base = {"local": t1, "visitante": t2, "fecha": fecha, "hora_col": hora,
                "ciudad": ciudad, "grupo": grp}
        if ft and len(ft) == 2:
            jugados.append({**base, "gl": int(ft[0]), "gv": int(ft[1])})
        else:
            fixture.append({**base, "neutral": True})
    return fixture, jugados, grupos


def leer_goleadores(equipos_wc):
    """Top goleador y % de penaltis (últimos 24 meses) por selección del Mundial."""
    ruta = _ruta("goleadores")
    if not os.path.exists(ruta):
        return {}, {}
    goles = defaultdict(Counter)   # equipo -> Counter(jugador)
    penaltis = defaultdict(lambda: [0, 0])  # equipo -> [penaltis, total]
    desde = date(FECHA_REF.year - 2, FECHA_REF.month, FECHA_REF.day)
    with open(ruta, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            try:
                fecha = datetime.strptime(fila["date"], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            if fecha < desde:
                continue
            eq = normalizar(fila.get("team", ""))
            if eq not in equipos_wc:
                continue
            jug = fila.get("scorer", "").strip()
            if jug and fila.get("own_goal", "").upper() != "TRUE":
                goles[eq][jug] += 1
            penaltis[eq][1] += 1
            if fila.get("penalty", "").upper() == "TRUE":
                penaltis[eq][0] += 1
    top = {eq: c.most_common(1)[0] for eq, c in goles.items() if c}
    pen = {eq: (v[0] / v[1] if v[1] else 0.0) for eq, v in penaltis.items()}
    return top, pen


def leer_goleadores_probables(equipos_wc):
    """
    Top-5 goleadores (últimos 24 meses) por selección, con su número de goles y
    el total de goles del equipo. Sirve para estimar el goleador más probable:
    la cuota de goles de cada jugador reparte el xG del equipo en el partido.
    """
    ruta = _ruta("goleadores")
    if not os.path.exists(ruta):
        return {}
    goles = defaultdict(Counter)
    desde = date(FECHA_REF.year - 2, FECHA_REF.month, FECHA_REF.day)
    with open(ruta, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            try:
                fecha = datetime.strptime(fila["date"], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            if fecha < desde:
                continue
            eq = normalizar(fila.get("team", ""))
            if eq not in equipos_wc:
                continue
            jug = fila.get("scorer", "").strip()
            if jug and fila.get("own_goal", "").upper() != "TRUE":
                goles[eq][jug] += 1
    salida = {}
    for eq, c in goles.items():
        total = sum(c.values())
        salida[eq] = {"total": total, "top": c.most_common(5)}
    return salida


def leer_tarjetas_wc(equipos_wc):
    """
    Tasa de tarjetas por partido en Mundiales (jfjelstul/bookings.csv).
    Respaldo para selecciones sin cobertura de StatsBomb en event_rates.json.
    Devuelve {equipo: {"amarillas": x, "rojas": y}} por partido.
    """
    ruta = _ruta("tarjetas_wc")
    if not os.path.exists(ruta):
        return {}
    am = defaultdict(int); ro = defaultdict(int); partidos = defaultdict(set)
    with open(ruta, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            eq = normalizar(fila.get("team_name", ""))
            if eq not in equipos_wc:
                continue
            mid = fila.get("match_id", "")
            if mid:
                partidos[eq].add(mid)
            if fila.get("yellow_card") == "1" and fila.get("second_yellow_card") != "1":
                am[eq] += 1
            if fila.get("red_card") == "1" or fila.get("sending_off") == "1" \
               or fila.get("second_yellow_card") == "1":
                ro[eq] += 1
    salida = {}
    for eq in partidos:
        pj = len(partidos[eq]) or 1
        salida[eq] = {"amarillas": am[eq] / pj, "rojas": ro[eq] / pj}
    return salida


def leer_event_rates():
    """
    Tasas de tiros/córners/tarjetas/xG por selección (data/event_rates.json),
    precalculadas con agregar_eventos.py desde StatsBomb Open Data y versionadas.
    """
    ruta = os.path.join(DIR_DATOS, "event_rates.json")
    if not os.path.exists(ruta):
        return {"liga": {}, "equipos": {}}
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def leer_player_rates():
    """
    Datos por jugador (xG real, goles, tiros ponderados por recencia) desde
    data/player_rates.json. Permite estimar el goleador probable según la
    calidad de tiro de cada jugador, no según una cuota plana de goles.
    """
    ruta = os.path.join(DIR_DATOS, "player_rates.json")
    if not os.path.exists(ruta):
        return {"equipos": {}}
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def leer_tandas(equipos_wc):
    """Récord en tandas de penaltis (histórico) por selección."""
    ruta = _ruta("tandas")
    if not os.path.exists(ruta):
        return {}
    rec = defaultdict(lambda: [0, 0])  # equipo -> [ganadas, total]
    with open(ruta, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            l, v = normalizar(fila.get("home_team", "")), normalizar(fila.get("away_team", ""))
            w = normalizar(fila.get("winner", ""))
            for eq in (l, v):
                if eq in equipos_wc:
                    rec[eq][1] += 1
                    if eq == w:
                        rec[eq][0] += 1
    return {eq: tuple(v) for eq, v in rec.items()}


def leer_pedigri_mundial(equipos_wc):
    """Partidos jugados y ganados en Mundiales (histórico) por selección."""
    ruta = _ruta("mundiales")
    if not os.path.exists(ruta):
        return {}
    rec = defaultdict(lambda: [0, 0])  # equipo -> [jugados, ganados]
    with open(ruta, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            h = normalizar(fila.get("home_team_name", ""))
            a = normalizar(fila.get("away_team_name", ""))
            hw = fila.get("home_team_win", "0") == "1"
            aw = fila.get("away_team_win", "0") == "1"
            for eq, gan in ((h, hw), (a, aw)):
                if eq in equipos_wc:
                    rec[eq][0] += 1
                    if gan:
                        rec[eq][1] += 1
    return {eq: tuple(v) for eq, v in rec.items()}


# ---------------------------------------------------------------------------
# 5 fuentes nuevas
# ---------------------------------------------------------------------------

def leer_experiencia_plantillas(equipos_wc):
    """Cuenta jugadores únicos por selección en los 3 últimos Mundiales (profundidad WC)."""
    ruta = os.path.join(DIR_DATOS, "wc_squads.csv")
    if not os.path.exists(ruta):
        return {}
    recientes = {"WC-2014", "WC-2018", "WC-2022"}
    jugadores = defaultdict(set)
    with open(ruta, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila.get("tournament_id") not in recientes:
                continue
            eq = normalizar(fila.get("team_name", ""))
            pid = fila.get("player_id", "")
            if eq and pid:
                jugadores[eq].add(pid)
    return {e: len(jugadores.get(e, set())) for e in equipos_wc}


def leer_forma_wc2022(equipos_wc):
    """Forma en la fase de grupos del Mundial 2022 (puntos / máximo posible)."""
    ruta = os.path.join(DIR_DATOS, "worldcup_2022.json")
    if not os.path.exists(ruta):
        return {}
    with open(ruta, encoding="utf-8") as f:
        d = json.load(f)
    pts = defaultdict(int)
    jugados = defaultdict(int)
    for m in d.get("matches", []):
        if not str(m.get("round", "")).startswith("Matchday"):
            continue
        ft = (m.get("score") or {}).get("ft")
        if not ft or len(ft) != 2:
            continue
        t1, t2 = normalizar(m.get("team1", "")), normalizar(m.get("team2", ""))
        g1, g2 = ft[0], ft[1]
        jugados[t1] += 1; jugados[t2] += 1
        if g1 > g2:
            pts[t1] += 3
        elif g1 == g2:
            pts[t1] += 1; pts[t2] += 1
        else:
            pts[t2] += 3
    return {e: pts.get(e, 0) / (jugados[e] * 3.0)
            for e in equipos_wc if jugados.get(e, 0) > 0}


def leer_goles_pm_wc(equipos_wc):
    """Goles marcados por partido en Mundiales (tradición atacante histórica)."""
    ruta_g = os.path.join(DIR_DATOS, "wc_goals.csv")
    ruta_h = os.path.join(DIR_DATOS, "wc_history.csv")
    if not os.path.exists(ruta_g) or not os.path.exists(ruta_h):
        return {}
    goles = defaultdict(int)
    with open(ruta_g, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila.get("own_goal") == "1":
                continue
            eq = normalizar(fila.get("player_team_name", ""))
            if eq:
                goles[eq] += 1
    partidos = defaultdict(int)
    with open(ruta_h, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            for k in ("home_team_name", "away_team_name"):
                eq = normalizar(fila.get(k, ""))
                if eq:
                    partidos[eq] += 1
    return {e: goles.get(e, 0) / partidos[e]
            for e in equipos_wc if partidos.get(e, 0) >= 3}


def leer_posicion_wc(equipos_wc):
    """Posición media ponderada en los últimos 3 Mundiales (1=campeón, 32=eliminado en grupos)."""
    ruta = os.path.join(DIR_DATOS, "wc_standings.csv")
    if not os.path.exists(ruta):
        return {}
    pesos = {"WC-2022": 1.0, "WC-2018": 0.6, "WC-2014": 0.4}
    datos = defaultdict(list)
    with open(ruta, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            tid = fila.get("tournament_id", "")
            if tid not in pesos:
                continue
            eq = normalizar(fila.get("team_name", ""))
            try:
                pos = int(fila["position"])
            except (ValueError, KeyError):
                continue
            if eq:
                datos[eq].append((pos, pesos[tid]))
    result = {}
    for e in equipos_wc:
        d = datos.get(e, [])
        if d:
            tw = sum(w for _, w in d)
            result[e] = sum(p * w for p, w in d) / tw
    return result


def leer_forma_euro2024(equipos_wc):
    """Forma de equipos europeos en la Eurocopa 2024 (puntos / máximo posible)."""
    ruta = os.path.join(DIR_DATOS, "euro_2024.json")
    if not os.path.exists(ruta):
        return {}
    with open(ruta, encoding="utf-8") as f:
        d = json.load(f)
    pts = defaultdict(int)
    jugados = defaultdict(int)
    for m in d.get("matches", []):
        ft = (m.get("score") or {}).get("ft")
        if not ft or len(ft) != 2:
            continue
        t1, t2 = normalizar(m.get("team1", "")), normalizar(m.get("team2", ""))
        g1, g2 = ft[0], ft[1]
        jugados[t1] += 1; jugados[t2] += 1
        if g1 > g2:
            pts[t1] += 3
        elif g1 == g2:
            pts[t1] += 1; pts[t2] += 1
        else:
            pts[t2] += 3
    return {e: min(pts.get(e, 0) / (jugados[e] * 3.0), 1.0)
            for e in equipos_wc if jugados.get(e, 0) > 0}


def calcular_factor_wc(equipos_wc, exp_plant, forma_wc22, goles_pm,
                        pos_wc, forma_euro24):
    """
    Combina las 5 fuentes nuevas en un factor multiplicador por equipo.
    Centrado en 1.0; rango efectivo ≈ 0.88–1.12 (±12%).
    """
    factor = {}
    for e in equipos_wc:
        scores = []

        # 1. Profundidad de plantilla mundialista (0-1)
        if exp_plant:
            scores.append(min(exp_plant.get(e, 0) / 28.0, 1.0))

        # 2. Forma Qatar 2022 (0-1)
        if e in forma_wc22:
            scores.append(forma_wc22[e])

        # 3. Tradición goleadora en Mundiales (0-1)
        if goles_pm:
            scores.append(min(goles_pm.get(e, 1.0) / 2.0, 1.0))

        # 4. Posición histórica en Mundiales (top-4 → bonus; solo semifinalistas en datos)
        if e in pos_wc:
            scores.append(max(0.0, 1.0 - (pos_wc[e] - 1.0) / 3.0))

        # 5. Forma Eurocopa 2024 (sólo equipos europeos)
        if e in forma_euro24:
            scores.append(forma_euro24[e])

        if not scores:
            factor[e] = 1.0
            continue

        avg = sum(scores) / len(scores)
        factor[e] = 0.88 + 0.24 * avg   # [0.88, 1.12]
    return factor


# ===========================================================================
# ELO (World Football Elo, computado del historial completo)
# ===========================================================================

def k_torneo(torneo):
    if torneo == "FIFA World Cup":
        return 60
    if "World Cup qualification" in torneo:
        return 45
    if torneo in ("UEFA Euro", "Copa América", "African Cup of Nations",
                  "AFC Asian Cup", "Gold Cup", "UEFA Nations League"):
        return 50
    if "qualification" in torneo:
        return 40
    if torneo == "Friendly":
        return 20
    return 30


def calcular_elo(partidos):
    """
    Recalcula el Elo de cada selección recorriendo todo el historial en orden
    cronológico. Fórmula World Football Elo: K por importancia del torneo,
    multiplicador por diferencia de goles y ventaja de local.
    """
    elo = defaultdict(lambda: ELO_INICIAL)
    for p in partidos:
        if p["gl"] is None or p["gv"] is None:
            continue
        rl, rv = elo[p["local"]], elo[p["visitante"]]
        dr = rl + (0 if p["neutral"] else ELO_HFA) - rv
        we = 1.0 / (10 ** (-dr / 400.0) + 1.0)          # esperado local
        w = 1.0 if p["gl"] > p["gv"] else 0.5 if p["gl"] == p["gv"] else 0.0
        gd = abs(p["gl"] - p["gv"])
        g = 1.0 if gd <= 1 else 1.5 if gd == 2 else (11 + gd) / 8.0
        k = k_torneo(p["torneo"])
        cambio = k * g * (w - we)
        elo[p["local"]] += cambio
        elo[p["visitante"]] -= cambio
    return dict(elo)


# ===========================================================================
# Modelo de fuerza (Poisson tipo Dixon-Coles, anclado a Elo + FIFA)
# ===========================================================================

def peso_recencia(fecha):
    return 0.5 ** ((FECHA_REF - fecha).days / VIDA_MEDIA_DIAS)


def peso_torneo(torneo):
    if torneo == "Friendly":
        return 0.5
    if torneo in ("FIFA World Cup", "UEFA Euro", "Copa América",
                  "African Cup of Nations", "AFC Asian Cup", "Gold Cup"):
        return 1.5
    if "qualification" in torneo or "Nations League" in torneo:
        return 1.2
    return 1.0


def calcular_fuerzas(partidos, elo, ranking_fifa, equipos_ancla, factor_wc=None):
    """
    Ataque/defensa por selección. El 'ancla' combina Elo (principal), ranking
    FIFA y el factor mundialista (5 fuentes nuevas), calibrados contra la mediana
    de las selecciones del Mundial. El ajuste iterativo de goles refina ese ancla.
    """
    if factor_wc is None:
        factor_wc = {}

    relevantes = [p for p in partidos
                  if p["gl"] is not None and p["gv"] is not None
                  and 0 <= (FECHA_REF - p["fecha"]).days <= VENTANA_DIAS]

    muestras, equipos, sg, sp = [], set(), 0.0, 0.0
    for p in relevantes:
        w = peso_recencia(p["fecha"]) * peso_torneo(p["torneo"])
        equipos.add(p["local"]); equipos.add(p["visitante"])
        muestras.append((w, p["local"], p["visitante"], p["gl"], p["gv"]))
        muestras.append((w, p["visitante"], p["local"], p["gv"], p["gl"]))
        sg += w * (p["gl"] + p["gv"]); sp += 2 * w
    liga = sg / sp if sp else 1.3

    # Medianas de referencia entre las selecciones del Mundial.
    elos_wc = sorted(elo.get(e, ELO_INICIAL) for e in equipos_ancla)
    elo_med = elos_wc[len(elos_wc) // 2] if elos_wc else ELO_INICIAL
    fifa_vals = sorted(ranking_fifa.values())
    fifa_med = fifa_vals[len(fifa_vals) // 2] if fifa_vals else 1500.0

    def ancla(e):
        # Elo 60% · FIFA 20% · factor mundialista (5 fuentes nuevas) 20%
        m_elo = 10 ** ((elo.get(e, ELO_INICIAL) - elo_med) / 600.0)
        pts = ranking_fifa.get(e)
        m_fifa = (pts / fifa_med) if pts else 1.0
        m_wc = factor_wc.get(e, 1.0)
        m = (m_elo ** 0.60) * (m_fifa ** 0.20) * (m_wc ** 0.20)
        return max(0.35, min(2.8, m))

    por_equipo = defaultdict(list)
    for w, e, r, gf, gc in muestras:
        por_equipo[e].append((w, r, gf, gc))

    ataque  = {e: ancla(e) for e in equipos}
    defensa = {e: 1.0 / ancla(e) for e in equipos}
    for _ in range(80):
        na, nd = {}, {}
        for e in equipos:
            a_n = PRIOR_PARTIDOS * liga * ancla(e)
            a_d = PRIOR_PARTIDOS * liga
            d_n = PRIOR_PARTIDOS * liga / ancla(e)
            d_d = PRIOR_PARTIDOS * liga
            for w, r, gf, gc in por_equipo.get(e, []):
                a_n += w * gf; a_d += w * liga * defensa.get(r, 1.0)
                d_n += w * gc; d_d += w * liga * ataque.get(r, 1.0)
            na[e] = a_n / a_d if a_d else 1.0
            nd[e] = d_n / d_d if d_d else 1.0
        ma = sum(na.values()) / len(na); md = sum(nd.values()) / len(nd)
        ataque  = {e: v / ma for e, v in na.items()}
        defensa = {e: v / md for e, v in nd.items()}

    # Mezcla final ancla <-> goles, y re-normalización.
    for e in equipos:
        a = ancla(e)
        ataque[e]  = ALFA_ANCLA * a + (1 - ALFA_ANCLA) * ataque[e]
        defensa[e] = ALFA_ANCLA * (1.0 / a) + (1 - ALFA_ANCLA) * defensa[e]
    ma = sum(ataque.values()) / len(ataque); md = sum(defensa.values()) / len(defensa)
    ataque  = {e: v / ma for e, v in ataque.items()}
    defensa = {e: v / md for e, v in defensa.items()}
    return ataque, defensa, liga


# ===========================================================================
# Predicción por partido
# ===========================================================================

def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def predecir_partido(local, visitante, ataque, defensa, liga, ventaja_local):
    a_loc, d_loc = ataque.get(local, 1.0), defensa.get(local, 1.0)
    a_vis, d_vis = ataque.get(visitante, 1.0), defensa.get(visitante, 1.0)
    xg_loc = liga * a_loc * d_vis
    xg_vis = liga * a_vis * d_loc
    if ventaja_local:
        xg_loc *= VENTAJA_LOCAL
        xg_vis /= VENTAJA_LOCAL ** 0.5

    pl = [poisson_pmf(i, xg_loc) for i in range(MAX_GOLES + 1)]
    pv = [poisson_pmf(j, xg_vis) for j in range(MAX_GOLES + 1)]
    mejor_ij, mejor_p = (0, 0), -1.0
    p_l = p_e = p_v = 0.0
    for i in range(MAX_GOLES + 1):
        for j in range(MAX_GOLES + 1):
            pij = pl[i] * pv[j]
            if pij > mejor_p:
                mejor_p, mejor_ij = pij, (i, j)
            if i > j:   p_l += pij
            elif i == j: p_e += pij
            else:        p_v += pij
    tot = p_l + p_e + p_v
    return {
        "xg_local": round(xg_loc, 2), "xg_visitante": round(xg_vis, 2),
        "marcador_local": mejor_ij[0], "marcador_visitante": mejor_ij[1],
        "prob_marcador": round(mejor_p * 100, 1),
        "prob_local": round(p_l / tot * 100, 1),
        "prob_empate": round(p_e / tot * 100, 1),
        "prob_visitante": round(p_v / tot * 100, 1),
    }


# ===========================================================================
# Predicción de estadísticas por partido (tiros, córners, tarjetas, goleador)
# ===========================================================================

PRIOR_EVENTOS = 4.0   # regularización: partidos-equivalentes hacia el promedio de liga


def _tasa(rates, equipo, clave, defecto):
    """
    Tasa por partido de una selección, regularizada hacia el promedio de liga
    según el tamaño de muestra (selecciones con pocos partidos se acercan a la
    media; evita valores ruidosos como '4.7 amarillas' con 2-3 partidos).
    """
    liga = rates.get("liga", {}).get(clave, defecto)
    eq = rates.get("equipos", {}).get(equipo)
    if eq and clave in eq:
        pj = eq.get("pj", 0.0)
        return (pj * eq[clave] + PRIOR_EVENTOS * liga) / (pj + PRIOR_EVENTOS)
    return liga


def predecir_eventos(local, visitante, rates, tarjetas_wc, goleadores,
                     player_rates, pred):
    """
    Estima estadísticas del partido. Mejoras clave:

      - Tiros y tiros a puerta se DERIVAN del xG del partido (el mismo que fija
        el marcador), usando la relación real tiros/xG de cada equipo. Así más
        tiros implican más goles esperados — coherente, no inventado.
      - Las tarjetas (amarillas y prob. de roja) dependen del RIVAL: suben en
        partidos parejos (más intensos) y en cruces entre equipos fauleros.
      - El goleador probable usa el xG real por jugador (StatsBomb): reparte el
        xG del equipo según la calidad de tiro de cada jugador, no una cuota
        plana de goles. Cae a goalscorers.csv cuando no hay datos StatsBomb.

    'pred' es el dict de predecir_partido (xG del partido y probabilidades 1X2).
    """
    liga = rates.get("liga", {})
    L_TIROS  = liga.get("tiros_f", 12.0) or 12.0
    L_PUERTA = liga.get("puerta_f", 4.0) or 4.0
    L_CORNER = liga.get("corners_f", 5.0) or 5.0
    L_XG     = liga.get("xg_f", 1.3) or 1.3
    L_FALTAS = liga.get("faltas", 14.0) or 14.0

    xg_l, xg_v = pred["xg_local"], pred["xg_visitante"]

    # --- Tiros / córners: escala real del equipo, modulada por el dominio ---
    # base = tasa real (favor del equipo x en contra del rival), magnitud realista.
    # dominio = cuánto manda este equipo en el partido (según el xG del modelo),
    # con raíz para que las palizas no disparen los tiros a cifras irreales.
    def combinar(eq, riv, cf, cc, d):
        return (_tasa(rates, eq, cf, d) * _tasa(rates, riv, cc, d)) ** 0.5

    share_l = xg_l / ((xg_l + xg_v) or 1.0)
    dom_l = (2.0 * share_l) ** 0.7          # share .5->1.0, .8->1.39, .2->0.52
    dom_v = (2.0 * (1 - share_l)) ** 0.7

    tiros_l = combinar(local, visitante, "tiros_f", "tiros_c", L_TIROS) * dom_l
    tiros_v = combinar(visitante, local, "tiros_f", "tiros_c", L_TIROS) * dom_v
    tiros_l = max(3.0, min(27.0, tiros_l)); tiros_v = max(3.0, min(27.0, tiros_v))

    # tiros a puerta = tiros x tasa real de puntería del equipo (a puerta/tiros)
    def punteria(eq):
        t = _tasa(rates, eq, "tiros_f", L_TIROS)
        return (_tasa(rates, eq, "puerta_f", L_PUERTA) / t) if t else (L_PUERTA / L_TIROS)
    puerta_l = min(tiros_l, tiros_l * punteria(local))
    puerta_v = min(tiros_v, tiros_v * punteria(visitante))

    corner_l = combinar(local, visitante, "corners_f", "corners_c", L_CORNER) * (0.6 + 0.4 * dom_l)
    corner_v = combinar(visitante, local, "corners_f", "corners_c", L_CORNER) * (0.6 + 0.4 * dom_v)

    # --- Tarjetas dependientes del rival ---
    # Intensidad: partidos parejos (1X2 equilibrado) generan más tarjetas.
    cierre = 1.0 - abs(pred["prob_local"] - pred["prob_visitante"]) / 100.0
    intensidad = 0.85 + 0.40 * cierre               # 0.85 (paliza) .. 1.25 (parejo)
    # Cruce físico: media de faltas de ambos respecto a la liga.
    f_l = _tasa(rates, local, "faltas", L_FALTAS)
    f_v = _tasa(rates, visitante, "faltas", L_FALTAS)
    cruce = ((f_l + f_v) / (2 * L_FALTAS)) ** 0.5    # >1 si ambos faulean mucho

    def base_tarjeta(eq, clave, defecto):
        e = rates.get("equipos", {}).get(eq)
        if e and clave in e:
            return _tasa(rates, eq, clave, defecto)
        if eq in tarjetas_wc:
            return tarjetas_wc[eq][clave]
        return liga.get(clave, defecto)

    am_l = base_tarjeta(local, "amarillas", 2.0) * intensidad * cruce
    am_v = base_tarjeta(visitante, "amarillas", 2.0) * intensidad * cruce
    ro_l = base_tarjeta(local, "rojas", 0.1) * intensidad * cruce
    ro_v = base_tarjeta(visitante, "rojas", 0.1) * intensidad * cruce
    prob_roja_l = round((1 - math.exp(-ro_l)) * 100, 1)
    prob_roja_v = round((1 - math.exp(-ro_v)) * 100, 1)

    # --- Goleador probable ---
    # Con StatsBomb: cuota = 0.6 * (xG del jugador / xG del equipo)
    #                      + 0.4 * (goles del jugador / goles del equipo)
    # Mezclar xG y goles evita que un defensa con xG de balón parado supere a un
    # delantero, y premia a quien de verdad define. Cae a goalscorers.csv si no hay datos.
    def probables(eq, xg_eq):
        pr = player_rates.get("equipos", {}).get(eq)
        cand = []
        if pr and pr.get("total_xg", 0) > 0 and pr.get("jugadores"):
            txg = pr["total_xg"]; tgo = pr.get("total_goles", 0) or 0
            for j in pr["jugadores"]:
                s_xg = j["xg"] / txg
                s_go = (j["goles"] / tgo) if tgo > 0 else s_xg
                cand.append((j["nombre"], 0.6 * s_xg + 0.4 * s_go))
            cand.sort(key=lambda x: -x[1])
        else:
            info = goleadores.get(eq)
            if not info or not info["top"] or info["total"] <= 0:
                return []
            cand = [(jug, g / info["total"]) for jug, g in info["top"]]
        out = []
        for nombre, cuota in cand[:3]:
            p = 1 - math.exp(-xg_eq * cuota)
            out.append({"jugador": nombre, "prob": round(p * 100)})
        return out

    return {
        "tiros_local": round(tiros_l), "tiros_visitante": round(tiros_v),
        "tiros_puerta_local": round(puerta_l), "tiros_puerta_visitante": round(puerta_v),
        "corners_local": round(corner_l), "corners_visitante": round(corner_v),
        "amarillas_local": round(am_l, 1), "amarillas_visitante": round(am_v, 1),
        "prob_roja_local": prob_roja_l, "prob_roja_visitante": prob_roja_v,
        "goleadores_local": probables(local, xg_l),
        "goleadores_visitante": probables(visitante, xg_v),
    }


# ===========================================================================
# Orquestación
# ===========================================================================

def generar(offline=False):
    print("Descargando fuentes de datos...")
    descargar_todo(offline=offline)
    cargar_exnombres()

    partidos = leer_resultados()
    ranking_fifa = leer_ranking_fifa()
    fixture, jugados, grupos = leer_fixture_wc()
    equipos_wc = set(grupos)

    elo = calcular_elo(partidos)
    top_goleador, tasa_penal = leer_goleadores(equipos_wc)
    tandas = leer_tandas(equipos_wc)
    pedigri = leer_pedigri_mundial(equipos_wc)

    # 5 fuentes nuevas
    exp_plant  = leer_experiencia_plantillas(equipos_wc)
    forma_wc22 = leer_forma_wc2022(equipos_wc)
    goles_pm   = leer_goles_pm_wc(equipos_wc)
    pos_wc     = leer_posicion_wc(equipos_wc)
    forma_euro = leer_forma_euro2024(equipos_wc)
    factor_wc  = calcular_factor_wc(equipos_wc, exp_plant, forma_wc22,
                                     goles_pm, pos_wc, forma_euro)

    # Estadísticas por evento (tiros, córners, tarjetas, goleador probable)
    event_rates  = leer_event_rates()
    player_rates = leer_player_rates()
    tarjetas_wc  = leer_tarjetas_wc(equipos_wc)
    goleadores   = leer_goleadores_probables(equipos_wc)
    n_cobertura = sum(1 for e in equipos_wc if e in event_rates.get("equipos", {}))

    print(f"\nHistórico: {len(partidos)} partidos | WC2026: {len(jugados)} jugados, {len(fixture)} pendientes")
    print(f"Estadísticas por evento (StatsBomb): {n_cobertura}/{len(equipos_wc)} selecciones con datos propios")

    ataque, defensa, liga = calcular_fuerzas(partidos, elo, ranking_fifa,
                                              equipos_wc, factor_wc)

    # Info por selección (para la UI y verificación)
    info_equipos = {}
    for e in equipos_wc:
        tg = top_goleador.get(e)
        info_equipos[e] = {
            "bandera": bandera(e),
            "elo": round(elo.get(e, ELO_INICIAL)),
            "grupo": grupos[e],
            "top_goleador": tg[0] if tg else "",
            "top_goleador_goles": tg[1] if tg else 0,
            "tasa_penal": round(tasa_penal.get(e, 0.0) * 100),
            "tandas": tandas.get(e, (0, 0)),
            "mundial": pedigri.get(e, (0, 0)),
            "exp_wc": exp_plant.get(e, 0),
            "forma_wc22": round(forma_wc22.get(e, 0.0) * 100),
            "goles_wc_pm": round(goles_pm.get(e, 0.0), 2),
            "pos_wc_hist": round(pos_wc.get(e, 0.0), 1),
            "factor_wc": round(factor_wc.get(e, 1.0), 3),
        }

    print("\nTop 12 por Elo (selecciones del Mundial):")
    for e in sorted(equipos_wc, key=lambda x: elo.get(x, 0), reverse=True)[:12]:
        print(f"  {e:24} Elo={elo.get(e,0):.0f}  ataque={ataque[e]:.2f} def={defensa[e]:.2f}")

    predicciones = []
    for p in fixture:
        pred = predecir_partido(p["local"], p["visitante"], ataque, defensa, liga, not p["neutral"])
        eventos = predecir_eventos(p["local"], p["visitante"], event_rates,
                                   tarjetas_wc, goleadores, player_rates, pred)
        predicciones.append({
            "grupo": p["grupo"], "fecha": p["fecha"].isoformat() if p["fecha"] else "",
            "hora_col": p["hora_col"], "ciudad": p["ciudad"],
            "local": p["local"], "visitante": p["visitante"],
            "bandera_local": bandera(p["local"]), "bandera_visitante": bandera(p["visitante"]),
            "elo_local": round(elo.get(p["local"], ELO_INICIAL)),
            "elo_visitante": round(elo.get(p["visitante"], ELO_INICIAL)),
            **pred,
            **eventos,
        })
    predicciones.sort(key=lambda x: (x["grupo"], x["fecha"], x["hora_col"], x["local"]))

    for j in jugados:
        j["bandera_local"] = bandera(j["local"])
        j["bandera_visitante"] = bandera(j["visitante"])
        if j["fecha"]:
            j["fecha"] = j["fecha"].isoformat()

    print(f"\nPredicciones: {len(predicciones)}")
    _escribir_json(predicciones, jugados, info_equipos, liga)
    _escribir_texto(predicciones, jugados)
    _escribir_html(predicciones, jugados, info_equipos, liga)
    print("Listo: data/predictions.json, predicciones.txt, index.html")


def _serial(o):
    return o.isoformat() if isinstance(o, date) else str(o)


def _escribir_json(predicciones, jugados, info_equipos, liga):
    out = {"generado": FECHA_REF.isoformat(), "promedio_liga": round(liga, 3),
           "equipos": info_equipos, "ya_jugados": jugados, "predicciones": predicciones}
    with open(os.path.join(DIR_DATOS, "predictions.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=_serial)


def _escribir_texto(predicciones, jugados):
    L = []
    L.append("=" * 66)
    L.append("  PROYECCIÓN — FASE DE GRUPOS MUNDIAL 2026")
    L.append(f"  Generado: {FECHA_REF.isoformat()}  ·  horario Colombia (UTC-5)")
    L.append(f"  Modelo: Elo + Poisson Dixon-Coles  ·  14 fuentes de datos")
    L.append("=" * 66)
    if jugados:
        L.append("\n--- RESULTADOS YA CONOCIDOS ---")
        for j in sorted(jugados, key=lambda x: (str(x.get("fecha") or ""), x.get("hora_col", ""))):
            L.append(f"  {j['fecha']}  {j.get('hora_col',''):>5} COL  {j['local']:>22}  "
                     f"{j['gl']}-{j['gv']}  {j['visitante']:<22} [{j['grupo']}]")
    g = None
    for p in predicciones:
        if p["grupo"] != g:
            g = p["grupo"]; L.append(f"\n--- {g} ---")
        marc = f"{p['marcador_local']}-{p['marcador_visitante']}"
        L.append(f"  {p['fecha']}  {p['hora_col']:>5} COL  {p['local']:>22}  {marc:^5}  "
                 f"{p['visitante']:<22} (L {p['prob_local']:.0f}% E {p['prob_empate']:.0f}% V {p['prob_visitante']:.0f}%)")
        # Línea de estadísticas estimadas
        if "tiros_local" in p:
            gl = p.get("goleadores_local") or []
            gv = p.get("goleadores_visitante") or []
            tg = " | goleador: "
            tg += (f"{gl[0]['jugador']} {gl[0]['prob']}%" if gl else "—")
            tg += " / "
            tg += (f"{gv[0]['jugador']} {gv[0]['prob']}%" if gv else "—")
            L.append(f"{'':>33}tiros {p['tiros_local']}-{p['tiros_visitante']} "
                     f"(a puerta {p['tiros_puerta_local']}-{p['tiros_puerta_visitante']}) · "
                     f"córners {p['corners_local']}-{p['corners_visitante']} · "
                     f"amarillas {p['amarillas_local']}-{p['amarillas_visitante']}{tg}")
    L.append("\nNOTA: marcador = resultado más probable (Poisson). Estimación, no certeza.")
    L.append("      El modelo acierta ~61% del resultado (1X2) y ~12% del marcador exacto.")
    L.append("      Tiros/córners/tarjetas = promedio esperado según tasas reales (StatsBomb).")
    texto = "\n".join(L)
    with open(os.path.join(DIR_BASE, "predicciones.txt"), "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    print("\n" + texto[:1500] + "\n  [...]")


def _escribir_html(predicciones, jugados, info_equipos, liga):
    datos = json.dumps({"generado": FECHA_REF.isoformat(), "promedio_liga": round(liga, 3),
                        "equipos": info_equipos, "ya_jugados": jugados,
                        "predicciones": predicciones}, ensure_ascii=False, default=_serial)
    html = _PLANTILLA_HTML.replace("/*__DATOS__*/", datos)
    with open(os.path.join(DIR_BASE, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


_PLANTILLA_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Polla Mundial 2026 — Proyección de marcadores</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700;800;900&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#0e1014; --bg2:#13161c; --surface:#171b22; --surface2:#1d222b;
    --line:#262c37; --ink:#f2f4f8; --muted:#8b93a3; --faint:#5b6372;
    --win:#37d399; --draw:#5b6372; --lose:#5b8cff; --accent:#ffce47;
    --shadow:0 1px 0 rgba(255,255,255,.03), 0 8px 24px rgba(0,0,0,.35);
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--ink);
       -webkit-font-smoothing:antialiased;line-height:1.4;padding-bottom:60px}
  .wrap{max-width:1180px;margin:0 auto;padding:0 20px}

  /* Header */
  header{border-bottom:1px solid var(--line);background:
         linear-gradient(180deg,var(--bg2),var(--bg));padding:30px 0 22px;margin-bottom:26px}
  .kicker{font:700 12px/1 'Archivo';letter-spacing:.22em;text-transform:uppercase;
          color:var(--accent);margin-bottom:10px}
  h1{font:800 34px/1.02 'Archivo';letter-spacing:-.02em}
  h1 .yr{color:var(--accent)}
  .lede{color:var(--muted);font-size:14px;margin-top:10px;max-width:680px}
  .stats{display:flex;gap:26px;margin-top:18px;flex-wrap:wrap}
  .stat .n{font:800 22px/1 'Archivo';color:var(--ink)}
  .stat .l{font-size:11px;color:var(--faint);text-transform:uppercase;letter-spacing:.08em;margin-top:4px}

  .legend{display:flex;gap:16px;align-items:center;font-size:12px;color:var(--muted);
          margin-top:20px;flex-wrap:wrap}
  .dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:middle}

  /* Section titles */
  .sec{font:700 13px/1 'Archivo';letter-spacing:.16em;text-transform:uppercase;
       color:var(--faint);margin:34px 0 16px;display:flex;align-items:center;gap:12px}
  .sec::after{content:"";flex:1;height:1px;background:var(--line)}

  /* Played results strip */
  .played{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
  .pcard{background:var(--surface);border:1px solid var(--line);border-radius:12px;
         padding:12px 14px;position:relative;overflow:hidden}
  .pcard::before{content:"FINAL";position:absolute;top:10px;right:12px;font:700 9px 'Archivo';
                 letter-spacing:.14em;color:var(--win);opacity:.85}
  .prow{display:flex;align-items:center;gap:10px;padding:3px 0}
  .prow img{width:24px;height:18px;border-radius:2px;object-fit:cover;box-shadow:0 0 0 1px rgba(0,0,0,.4)}
  .prow .nm{flex:1;font-size:14px;font-weight:500}
  .prow .sc{font:800 18px 'Archivo';font-variant-numeric:tabular-nums;min-width:22px;text-align:center}
  .prow.w .nm,.prow.w .sc{color:var(--ink)} .prow.l .nm,.prow.l .sc{color:var(--faint)}
  .pmeta{font-size:11px;color:var(--faint);margin-top:8px;display:flex;justify-content:space-between}

  /* Groups grid */
  .groups{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(360px,1fr))}
  .group{background:var(--surface);border:1px solid var(--line);border-radius:14px;
         box-shadow:var(--shadow);overflow:hidden}
  .ghead{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;
         border-bottom:1px solid var(--line);background:var(--bg2)}
  .ghead .gname{font:800 16px 'Archivo';letter-spacing:.02em}
  .ghead .gtag{font-size:10px;color:var(--faint);text-transform:uppercase;letter-spacing:.1em}
  .gteams{display:flex;gap:6px;padding:10px 16px;border-bottom:1px solid var(--line);flex-wrap:wrap}
  .gteams .t{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--muted);
             background:var(--surface2);padding:3px 8px;border-radius:20px}
  .gteams .t img{width:16px;height:12px;border-radius:2px;object-fit:cover}

  .match{padding:13px 16px;border-bottom:1px solid var(--line)}
  .match:last-child{border-bottom:none}
  .mtop{display:flex;justify-content:space-between;font-size:11px;color:var(--faint);margin-bottom:9px}
  .mtop .xg{font-variant-numeric:tabular-nums}
  .mteams{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:10px}
  .side{display:flex;align-items:center;gap:9px;min-width:0}
  .side.h{justify-content:flex-end}
  .side img{width:28px;height:21px;border-radius:3px;object-fit:cover;box-shadow:0 0 0 1px rgba(0,0,0,.4);flex-shrink:0}
  .side .nm{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .side.h .nm{text-align:right}
  .score{display:flex;align-items:center;gap:7px;background:var(--surface2);
          border:1px solid var(--line);border-radius:9px;padding:5px 11px}
  .score b{font:800 20px 'Archivo';font-variant-numeric:tabular-nums}
  .score .dash{color:var(--faint);font-weight:700}
  .bar{display:flex;height:6px;border-radius:4px;overflow:hidden;margin-top:11px;background:var(--bg)}
  .bar i{display:block;height:100%}
  .bar .bl{background:var(--win)} .bar .bd{background:var(--draw)} .bar .bv{background:var(--lose)}
  .plabels{display:flex;justify-content:space-between;font-size:10.5px;margin-top:6px;color:var(--faint);
           font-variant-numeric:tabular-nums}
  .plabels b{color:var(--muted);font-weight:600}

  /* Detalle de estadísticas por partido */
  .det{margin-top:11px}
  .det>summary{list-style:none;cursor:pointer;font:600 11px 'Archivo';letter-spacing:.08em;
       text-transform:uppercase;color:var(--faint);padding:6px 0;display:flex;align-items:center;gap:6px}
  .det>summary::-webkit-details-marker{display:none}
  .det>summary::before{content:"▸";color:var(--accent);font-size:10px;transition:transform .15s}
  .det[open]>summary::before{transform:rotate(90deg)}
  .det>summary:hover{color:var(--muted)}
  .stat-rows{padding:4px 0 2px}
  .srow{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:8px;padding:4px 0;
        font-size:12px;font-variant-numeric:tabular-nums}
  .srow .lv{text-align:right;color:var(--ink);font-weight:600}
  .srow .rv{text-align:left;color:var(--ink);font-weight:600}
  .srow .lb{font-size:10px;color:var(--faint);text-transform:uppercase;letter-spacing:.06em;text-align:center;white-space:nowrap}
  .srow .sbar{grid-column:1/-1;display:flex;height:4px;border-radius:3px;overflow:hidden;background:var(--bg);margin-top:1px}
  .srow .sbar i{display:block;height:100%}
  .srow .sbar .a{background:var(--win)} .srow .sbar .b{background:var(--lose);opacity:.85}
  .scorers{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}
  .scol .sh{font-size:10px;color:var(--faint);text-transform:uppercase;letter-spacing:.06em;margin-bottom:5px}
  .scol .pl{display:flex;justify-content:space-between;font-size:12px;padding:2px 0;gap:8px}
  .scol .pl .pn{color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .scol .pl .pp{color:var(--accent);font-weight:600;font-variant-numeric:tabular-nums}
  .scol .pl.empty{color:var(--faint)}

  .note{margin-top:30px;padding:16px 18px;background:var(--surface);border:1px solid var(--line);
        border-left:3px solid var(--accent);border-radius:10px;font-size:13px;color:var(--muted);line-height:1.6}
  .note b{color:var(--ink)}
  footer{margin-top:26px;font-size:11px;color:var(--faint);text-align:center;line-height:1.8}

  @media(max-width:480px){h1{font-size:26px}.side .nm{font-size:13px}}
</style>
</head>
<body>
<header><div class="wrap">
  <div class="kicker">Polla de oficina · Proyección estadística</div>
  <h1>Mundial <span class="yr">2026</span> — Marcadores de la fase de grupos</h1>
  <p class="lede" id="lede"></p>
  <div class="stats" id="stats"></div>
  <div class="legend">
    <span><span class="dot" style="background:var(--win)"></span>Gana local</span>
    <span><span class="dot" style="background:var(--draw)"></span>Empate</span>
    <span><span class="dot" style="background:var(--lose)"></span>Gana visitante</span>
    <span style="color:var(--faint)">· xG = goles esperados · Elo = fuerza global</span>
  </div>
</div></header>

<div class="wrap">
  <div id="played-sec"></div>
  <div class="sec">Predicciones por grupo</div>
  <div class="groups" id="groups"></div>

  <div class="note" id="note"></div>
  <footer id="footer"></footer>
</div>

<script>
const D = /*__DATOS__*/;
const FLAG = c => c ? `https://flagcdn.com/w40/${c}.png` : "";
const esc = s => (s||"").replace(/[&<>]/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));

document.getElementById("lede").textContent =
  "Marcador y estadísticas (tiros, córners, tarjetas, goleador) de cada partido según un modelo "
  + "Elo + Poisson alimentado por 14 fuentes de datos. Se actualiza automáticamente cada noche a "
  + "medida que llegan los resultados. Horarios en hora de Colombia.";

document.getElementById("stats").innerHTML = [
  [D.predicciones.length, "Partidos por jugar"],
  [D.ya_jugados.length, "Ya disputados"],
  ["12", "Grupos"],
  ["14", "Fuentes de datos"],
].map(([n,l])=>`<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`).join("");

// Resultados jugados
if (D.ya_jugados.length){
  let h = '<div class="sec">Resultados confirmados</div><div class="played">';
  for (const j of D.ya_jugados){
    if(!j.local||!j.visitante) continue;
    const lw=j.gl>j.gv, vw=j.gv>j.gl;
    h += `<div class="pcard">
      <div class="prow ${lw?'w':(vw?'l':'')}"><img src="${FLAG(j.bandera_local)}" alt=""><span class="nm">${esc(j.local)}</span><span class="sc">${j.gl}</span></div>
      <div class="prow ${vw?'w':(lw?'l':'')}"><img src="${FLAG(j.bandera_visitante)}" alt=""><span class="nm">${esc(j.visitante)}</span><span class="sc">${j.gv}</span></div>
      <div class="pmeta"><span>${j.fecha||""}${j.hora_col?" · "+j.hora_col+" COL":""}</span><span>${esc(j.grupo)}</span></div>
    </div>`;
  }
  document.getElementById("played-sec").innerHTML = h + "</div>";
}

// Fila de estadística comparada (barra proporcional local vs visitante)
function srow(label, a, b){
  const na=parseFloat(a)||0, nb=parseFloat(b)||0, ta=(na+nb)||1;
  return `<div class="srow"><span class="lv">${a}</span><span class="lb">${label}</span><span class="rv">${b}</span>`
    + `<span class="sbar"><i class="a" style="width:${na/ta*100}%"></i><i class="b" style="width:${nb/ta*100}%"></i></span></div>`;
}
function colGoleadores(titulo, lista){
  let h = `<div class="scol"><div class="sh">${titulo}</div>`;
  if(!lista || !lista.length){ h += `<div class="pl empty">—</div>`; }
  else { for(const x of lista){ h += `<div class="pl"><span class="pn">${esc(x.jugador)}</span><span class="pp">${x.prob}%</span></div>`; } }
  return h + "</div>";
}
// Panel desplegable con tiros, tiros a puerta, córners, tarjetas y goleadores
function detalle(p){
  if(p.tiros_local===undefined) return "";
  return `<details class="det"><summary>Estadísticas estimadas del partido</summary>
    <div class="stat-rows">
      ${srow("Tiros", p.tiros_local, p.tiros_visitante)}
      ${srow("Tiros a puerta", p.tiros_puerta_local, p.tiros_puerta_visitante)}
      ${srow("Córners", p.corners_local, p.corners_visitante)}
      ${srow("Amarillas", p.amarillas_local, p.amarillas_visitante)}
      ${srow("Prob. roja", p.prob_roja_local+"%", p.prob_roja_visitante+"%")}
    </div>
    <div class="scorers">
      ${colGoleadores("Goleador — "+esc(p.local), p.goleadores_local)}
      ${colGoleadores("Goleador — "+esc(p.visitante), p.goleadores_visitante)}
    </div>
  </details>`;
}

// Grupos
const byG={};
for(const p of D.predicciones)(byG[p.grupo]||=[]).push(p);
const E = D.equipos||{};
let gh="";
for(const g of Object.keys(byG).sort()){
  const teams=[...new Set(byG[g].flatMap(m=>[m.local,m.visitante]))]
     .sort((a,b)=>(E[b]?.elo||0)-(E[a]?.elo||0));
  gh += `<div class="group"><div class="ghead">
      <span class="gname">${esc(g.replace('Group','Grupo'))}</span>
      <span class="gtag">${byG[g].length} partidos</span></div>
    <div class="gteams">${teams.map(t=>`<span class="t"><img src="${FLAG(E[t]?.bandera)}" alt="">${esc(t)}</span>`).join("")}</div>`;
  for(const p of byG[g]){
    gh += `<div class="match">
      <div class="mtop"><span>${p.fecha||""}${p.hora_col?" · "+p.hora_col+" COL":""}</span>
        <span class="xg">xG ${p.xg_local} – ${p.xg_visitante}${p.ciudad?" · "+esc(p.ciudad):""}</span></div>
      <div class="mteams">
        <div class="side h"><span class="nm">${esc(p.local)}</span><img src="${FLAG(p.bandera_local)}" alt=""></div>
        <div class="score"><b>${p.marcador_local}</b><span class="dash">–</span><b>${p.marcador_visitante}</b></div>
        <div class="side"><img src="${FLAG(p.bandera_visitante)}" alt=""><span class="nm">${esc(p.visitante)}</span></div>
      </div>
      <div class="bar"><i class="bl" style="width:${p.prob_local}%"></i><i class="bd" style="width:${p.prob_empate}%"></i><i class="bv" style="width:${p.prob_visitante}%"></i></div>
      <div class="plabels"><span><b>${p.prob_local}%</b> local</span><span><b>${p.prob_empate}%</b> empate</span><span><b>${p.prob_visitante}%</b> visitante</span></div>
      ${detalle(p)}
    </div>`;
  }
  gh += "</div>";
}
document.getElementById("groups").innerHTML = gh;

document.getElementById("note").innerHTML =
  "<b>Cómo leerlo.</b> El marcador es el resultado <em>más probable</em>, no una certeza. "
  + "En fútbol acertar el marcador exacto es muy difícil: este modelo acierta cerca del "
  + "<b>61% de los resultados</b> (quién gana/empata) y solo el <b>~12% de los marcadores exactos</b>, "
  + "a la par de los mejores modelos comerciales. Las <b>estadísticas estimadas</b> (tiros, córners, "
  + "tarjetas, goleador) salen de las tasas reales por partido de cada selección en sus últimos "
  + "torneos (StatsBomb): son <em>promedios esperados</em>, no predicciones exactas. Para la polla, "
  + "confía en el favorito y las probabilidades más que en el dato puntual.";

document.getElementById("footer").innerHTML =
  "Fuentes: martj42/international_results · Dato-Futbol/fifa-ranking · openfootball/worldcup.json 2026 · "
  + "openfootball/worldcup.json 2022 · openfootball/euro.json 2024 · "
  + "jfjelstul/worldcup (matches · squads · goals · standings · bookings) · StatsBomb Open Data · "
  + "goalscorers · shootouts · former_names · Elo computado.<br>"
  + "Banderas: flagcdn.com · Actualización automática diaria a las 12 am Colombia · Generado el "+D.generado+".";
</script>
</body>
</html>
"""

if __name__ == "__main__":
    generar(offline="--offline" in sys.argv)
