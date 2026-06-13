#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agregador de estadísticas por evento — StatsBomb Open Data
==========================================================

Descarga los eventos de los torneos de selecciones más recientes (StatsBomb
Open Data, CC BY-NC) y calcula:

  data/event_rates.json — por selección, tasas POR PARTIDO de:
    - tiros / tiros a puerta a favor y en contra
    - córners a favor / en contra
    - tarjetas amarillas, expulsiones, faltas cometidas
    - xG y goles a favor / en contra (para atar tiros<->goles de forma coherente)

  data/player_rates.json — por jugador (xG real, goles, tiros ponderados por
    recencia) para estimar el goleador probable según calidad de tiro, no según
    una cuota plana de goles.

Ambos pesan pocos KB y SÍ se versionan en git. Así predict.py predice las
estadísticas por partido sin descargar los ~360 MB de eventos en cada corrida.

Este script es pesado: córrelo manualmente (o con el workflow semanal) sólo
cuando haya un torneo nuevo. Las tasas por selección son estables entre días.

Uso:
    python3 agregar_eventos.py
"""

import json
import os
import urllib.request
from collections import defaultdict

DIR_BASE  = os.path.dirname(os.path.abspath(__file__))
DIR_DATOS = os.path.join(DIR_BASE, "data")
BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

# Torneos de selecciones a agregar, con peso de recencia.
# Los de 2024 pesan completo; el Mundial 2022 se usa como respaldo (peso menor)
# para cubrir selecciones (AFC/CONCACAF) ausentes en los torneos de 2024.
TORNEOS = [
    ("Copa America",            "2024", 1.0),
    ("UEFA Euro",               "2024", 1.0),
    ("African Cup of Nations",  "2023", 1.0),
    ("FIFA World Cup",          "2022", 0.6),
]

# Normalización de nombres (consistente con predict.py)
_NORM = {
    "USA": "United States", "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina", "IR Iran": "Iran",
    "Côte d'Ivoire": "Ivory Coast", "Congo DR": "DR Congo",
    "Korea Republic": "South Korea", "Korea DPR": "North Korea",
    "Kyrgyz Republic": "Kyrgyzstan", "Türkiye": "Turkey", "Cabo Verde": "Cape Verde",
    "China PR": "China", "Chinese Taipei": "Taiwan",
}

ON_TARGET = {"Goal", "Saved", "Saved to Post"}


def normalizar(n):
    n = (n or "").strip()
    return _NORM.get(n, n)


def get(url, reintentos=4):
    for i in range(reintentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except Exception as e:
            if i == reintentos - 1:
                raise
    return None


def competiciones_objetivo():
    comps = json.loads(get(f"{BASE}/competitions.json"))
    res = {}
    for c in comps:
        for nombre, temporada, peso in TORNEOS:
            if c["competition_name"] == nombre and c["season_name"] == temporada:
                res[(nombre, temporada, peso)] = (c["competition_id"], c["season_id"])
    return res


def procesar_partido(mid, acc, jugadores=None, apodos=None):
    """Acumula estadísticas de un partido en acc[equipo] y, si se pasa,
    estadísticas por jugador en jugadores[(equipo, jugador)]. Si se pasa apodos,
    registra el nombre corto (nickname) de cada jugador desde el lineup."""
    try:
        events = json.loads(get(f"{BASE}/events/{mid}.json"))
    except Exception as e:
        print(f"    aviso: no se pudo leer partido {mid} ({e})")
        return False

    if apodos is not None:
        try:
            for tm in json.loads(get(f"{BASE}/lineups/{mid}.json")):
                for pl in tm.get("lineup", []):
                    nombre = pl.get("player_name", "")
                    apodo = pl.get("player_nickname") or nombre
                    if nombre:
                        apodos[nombre] = apodo
        except Exception:
            pass  # el apodo es opcional; si falla, usamos el nombre completo

    equipos = set()
    tiros = defaultdict(int); a_puerta = defaultdict(int)
    corners = defaultdict(int); amarillas = defaultdict(int)
    rojas = defaultdict(int); faltas = defaultdict(int)
    xg = defaultdict(float); goles = defaultdict(int)

    for e in events:
        tn = normalizar(e.get("team", {}).get("name", ""))
        if not tn:
            continue
        equipos.add(tn)
        t = e["type"]["name"]
        if t == "Shot":
            tiros[tn] += 1
            sh = e.get("shot", {})
            xg_tiro = sh.get("statsbomb_xg", 0.0) or 0.0
            xg[tn] += xg_tiro
            es_gol = sh.get("outcome", {}).get("name") == "Goal"
            if sh.get("outcome", {}).get("name") in ON_TARGET:
                a_puerta[tn] += 1
            if es_gol:
                goles[tn] += 1
            # Acumulado por jugador (para goleador probable basado en xG real)
            jug = e.get("player", {}).get("name", "")
            if jug and jugadores is not None:
                p = jugadores[(tn, jug)]
                p["tiros"] += 1
                p["xg"]    += xg_tiro
                if es_gol:
                    p["goles"] += 1
        elif t == "Pass":
            if e.get("pass", {}).get("type", {}).get("name") == "Corner":
                corners[tn] += 1
        elif t == "Foul Committed":
            faltas[tn] += 1
            card = e.get("foul_committed", {}).get("card", {}).get("name")
            if card == "Yellow Card":
                amarillas[tn] += 1
            elif card in ("Red Card", "Second Yellow"):
                rojas[tn] += 1
        elif t == "Bad Behaviour":
            card = e.get("bad_behaviour", {}).get("card", {}).get("name")
            if card == "Yellow Card":
                amarillas[tn] += 1
            elif card in ("Red Card", "Second Yellow"):
                rojas[tn] += 1

    eqs = list(equipos)
    if len(eqs) != 2:
        return False
    for tn in eqs:
        rival = eqs[0] if eqs[1] == tn else eqs[1]
        a = acc[tn]
        a["partidos"]            += 1
        a["tiros_f"]             += tiros[tn]
        a["tiros_c"]             += tiros[rival]
        a["puerta_f"]            += a_puerta[tn]
        a["puerta_c"]            += a_puerta[rival]
        a["corners_f"]           += corners[tn]
        a["corners_c"]           += corners[rival]
        a["amarillas"]           += amarillas[tn]
        a["rojas"]               += rojas[tn]
        a["faltas"]              += faltas[tn]
        a["xg_f"]                += xg[tn]
        a["xg_c"]                += xg[rival]
        a["goles_f"]             += goles[tn]
        a["goles_c"]             += goles[rival]
    return True


def nuevo_acc():
    return defaultdict(lambda: defaultdict(float))


def main():
    os.makedirs(DIR_DATOS, exist_ok=True)
    objetivo = competiciones_objetivo()
    print("Torneos encontrados:")
    for k in objetivo:
        print(f"  {k[0]} {k[1]} (peso {k[2]})")

    acc = nuevo_acc()
    jugadores = defaultdict(lambda: defaultdict(float))  # (equipo,jugador) -> stats ponderadas
    apodos = {}                                          # nombre completo -> nombre corto
    total = 0
    for (nombre, temporada, peso), (cid, sid) in objetivo.items():
        try:
            matches = json.loads(get(f"{BASE}/matches/{cid}/{sid}.json"))
        except Exception as e:
            print(f"  aviso: sin partidos de {nombre} {temporada} ({e})")
            continue
        print(f"\n{nombre} {temporada}: {len(matches)} partidos")
        # Acumuladores por torneo, luego se mezclan con su peso de recencia
        acc_t = nuevo_acc()
        jug_t = defaultdict(lambda: defaultdict(float))
        ok = 0
        for m in matches:
            if procesar_partido(m["match_id"], acc_t, jug_t, apodos):
                ok += 1
        print(f"  procesados {ok}/{len(matches)}")
        total += ok
        for eq, d in acc_t.items():
            for k, v in d.items():
                acc[eq][k] += v * peso
        for key, d in jug_t.items():
            for k, v in d.items():
                jugadores[key][k] += v * peso

    # ---- Tasas por equipo (por partido) ----
    rates = {}
    suma = defaultdict(float); n_eq = 0
    for eq, d in acc.items():
        pj = d["partidos"]
        if pj <= 0:
            continue
        rates[eq] = {
            "pj":          round(pj, 1),
            "tiros_f":     round(d["tiros_f"] / pj, 2),
            "tiros_c":     round(d["tiros_c"] / pj, 2),
            "puerta_f":    round(d["puerta_f"] / pj, 2),
            "puerta_c":    round(d["puerta_c"] / pj, 2),
            "corners_f":   round(d["corners_f"] / pj, 2),
            "corners_c":   round(d["corners_c"] / pj, 2),
            "amarillas":   round(d["amarillas"] / pj, 2),
            "rojas":       round(d["rojas"] / pj, 3),
            "faltas":      round(d["faltas"] / pj, 2),
            "xg_f":        round(d["xg_f"] / pj, 3),
            "xg_c":        round(d["xg_c"] / pj, 3),
            "goles_f":     round(d["goles_f"] / pj, 3),
            "goles_c":     round(d["goles_c"] / pj, 3),
        }
        for k in ("tiros_f","tiros_c","puerta_f","puerta_c","corners_f",
                  "corners_c","amarillas","rojas","faltas","xg_f","xg_c",
                  "goles_f","goles_c"):
            suma[k] += rates[eq][k]
        n_eq += 1

    liga = {k: round(suma[k] / n_eq, 3) for k in suma} if n_eq else {}

    salida = {"liga": liga, "equipos": rates, "n_equipos": n_eq,
              "partidos_procesados": total}
    with open(os.path.join(DIR_DATOS, "event_rates.json"), "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    # ---- Datos por jugador (goleador probable basado en xG real) ----
    por_equipo = defaultdict(list)
    for (eq, jug), d in jugadores.items():
        por_equipo[eq].append((jug, d["xg"], d["goles"], d["tiros"]))
    player_rates = {}
    for eq, lst in por_equipo.items():
        total_xg = sum(x for _, x, _, _ in lst)
        total_goles = sum(g for _, _, g, _ in lst)
        lst.sort(key=lambda x: -x[1])  # por xG ponderado
        player_rates[eq] = {
            "total_xg": round(total_xg, 3),
            "total_goles": round(total_goles, 2),
            "jugadores": [
                {"nombre": apodos.get(j, j), "xg": round(x, 3),
                 "goles": round(g, 2), "tiros": round(t, 1)}
                for j, x, g, t in lst[:12]
            ],
        }
    with open(os.path.join(DIR_DATOS, "player_rates.json"), "w", encoding="utf-8") as f:
        json.dump({"equipos": player_rates}, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"Guardado: data/event_rates.json y data/player_rates.json")
    print(f"Selecciones con datos: {n_eq} | jugadores: {len(jugadores)} | partidos: {total}")
    print(f"Promedio liga: tiros={liga.get('tiros_f')} a_puerta={liga.get('puerta_f')} "
          f"xG={liga.get('xg_f')} corners={liga.get('corners_f')} amarillas={liga.get('amarillas')}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
