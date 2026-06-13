#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agregador de estadísticas por evento — StatsBomb Open Data
==========================================================

Descarga los eventos de los torneos de selecciones más recientes (StatsBomb
Open Data, CC BY-NC) y calcula, por selección, las tasas POR PARTIDO de:

    - tiros a favor / en contra
    - tiros a puerta a favor / en contra
    - córners a favor / en contra
    - tarjetas amarillas
    - expulsiones (roja directa o doble amarilla)
    - faltas cometidas

El resultado se guarda en data/event_rates.json (unos pocos KB), que SÍ se
versiona en git. Así predict.py puede predecir estadísticas por partido sin
descargar los ~360 MB de eventos en cada corrida del GitHub Action.

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


def procesar_partido(mid, acc):
    """Acumula estadísticas de un partido en acc[equipo]."""
    try:
        events = json.loads(get(f"{BASE}/events/{mid}.json"))
    except Exception as e:
        print(f"    aviso: no se pudo leer partido {mid} ({e})")
        return False

    equipos = set()
    tiros = defaultdict(int); a_puerta = defaultdict(int)
    corners = defaultdict(int); amarillas = defaultdict(int)
    rojas = defaultdict(int); faltas = defaultdict(int)

    for e in events:
        tn = normalizar(e.get("team", {}).get("name", ""))
        if not tn:
            continue
        equipos.add(tn)
        t = e["type"]["name"]
        if t == "Shot":
            tiros[tn] += 1
            if e.get("shot", {}).get("outcome", {}).get("name") in ON_TARGET:
                a_puerta[tn] += 1
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
    pesos = {}  # equipo -> peso acumulado (para promedio ponderado correcto)
    total = 0
    for (nombre, temporada, peso), (cid, sid) in objetivo.items():
        try:
            matches = json.loads(get(f"{BASE}/matches/{cid}/{sid}.json"))
        except Exception as e:
            print(f"  aviso: sin partidos de {nombre} {temporada} ({e})")
            continue
        print(f"\n{nombre} {temporada}: {len(matches)} partidos")
        # Acumulador por torneo, luego se mezcla con su peso
        acc_t = nuevo_acc()
        ok = 0
        for m in matches:
            if procesar_partido(m["match_id"], acc_t):
                ok += 1
        print(f"  procesados {ok}/{len(matches)}")
        total += ok
        # Mezclar acc_t en acc global con peso del torneo
        for eq, d in acc_t.items():
            for k, v in d.items():
                acc[eq][k] += v * peso
            pesos[eq] = pesos.get(eq, 0.0)  # marca de existencia

    # Calcular tasas por partido (ponderadas: dividimos por partidos ponderados)
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
        }
        for k in ("tiros_f","tiros_c","puerta_f","puerta_c","corners_f",
                  "corners_c","amarillas","rojas","faltas"):
            suma[k] += rates[eq][k]
        n_eq += 1

    # Promedios de liga (respaldo para selecciones sin cobertura)
    liga = {k: round(suma[k] / n_eq, 3) for k in suma} if n_eq else {}

    salida = {"liga": liga, "equipos": rates, "n_equipos": n_eq,
              "partidos_procesados": total}
    destino = os.path.join(DIR_DATOS, "event_rates.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"Guardado: data/event_rates.json")
    print(f"Selecciones con datos: {n_eq} | partidos procesados: {total}")
    print(f"Promedio liga: tiros={liga.get('tiros_f')} a_puerta={liga.get('puerta_f')} "
          f"corners={liga.get('corners_f')} amarillas={liga.get('amarillas')}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
