#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Predictor de marcadores - Fase de grupos del Mundial 2026
=========================================================

App sencilla y autocontenida (SOLO librería estándar de Python) que:

  1. Descarga el dataset abierto de resultados de partidos internacionales.
  2. Extrae el fixture oficial del Mundial 2026 y reconstruye los grupos
     automáticamente (sin hardcodear nada).
  3. Calcula la fuerza ofensiva/defensiva de cada selección usando solo los
     últimos 24 meses de partidos, ponderando por recencia.
  4. Estima, con una distribución de Poisson, el marcador MÁS PROBABLE de cada
     partido y las probabilidades de victoria / empate / derrota.
  5. Exporta una tabla de texto lista para enviar y un index.html standalone.

Uso:
    python3 predict.py            # descarga datos si hace falta y genera todo
    python3 predict.py --offline  # usa el CSV ya descargado en data/

NOTA: es una estimación estadística sobre la forma reciente, NO una certeza.
"""

import csv
import json
import math
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import date, datetime

# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------

URL_DATOS = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
DIR_BASE = os.path.dirname(os.path.abspath(__file__))
DIR_DATOS = os.path.join(DIR_BASE, "data")
CSV_LOCAL = os.path.join(DIR_DATOS, "results.csv")

# Fecha de referencia para "los últimos 24 meses" y para decidir qué partidos
# ya se jugaron. Por defecto, hoy.
FECHA_REF = date(2026, 6, 13)

VENTANA_DIAS = 730          # 24 meses de historial
VIDA_MEDIA_DIAS = 365.0     # cada año, el peso de un partido se reduce a la mitad
PRIOR_PARTIDOS = 4.0        # regularización: equivale a N partidos "promedio"
VENTAJA_LOCAL = 1.25        # multiplicador de goles esperados para el anfitrión real
MAX_GOLES = 8               # tope de la rejilla de Poisson (0..8 por equipo)

TORNEO_WC = "FIFA World Cup"


# --------------------------------------------------------------------------
# Carga de datos
# --------------------------------------------------------------------------

def descargar_datos(offline=False):
    """Devuelve la ruta al CSV, descargándolo si es necesario."""
    os.makedirs(DIR_DATOS, exist_ok=True)
    if offline:
        if not os.path.exists(CSV_LOCAL):
            sys.exit("ERROR: --offline pero no existe data/results.csv. Corre sin --offline una vez.")
        return CSV_LOCAL
    print(f"Descargando datos desde {URL_DATOS} ...")
    try:
        with urllib.request.urlopen(URL_DATOS, timeout=30) as r:
            contenido = r.read()
        with open(CSV_LOCAL, "wb") as f:
            f.write(contenido)
        print(f"  OK: guardado en {CSV_LOCAL}")
    except Exception as e:
        if os.path.exists(CSV_LOCAL):
            print(f"  Aviso: falló la descarga ({e}); uso copia local.")
        else:
            sys.exit(f"ERROR: no pude descargar datos y no hay copia local: {e}")
    return CSV_LOCAL


def leer_partidos(ruta_csv):
    """Lee el CSV y devuelve una lista de dicts con los partidos."""
    partidos = []
    with open(ruta_csv, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            try:
                fecha = datetime.strptime(fila["date"], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            partidos.append({
                "fecha": fecha,
                "local": fila["home_team"].strip(),
                "visitante": fila["away_team"].strip(),
                "gl": _a_int(fila["home_score"]),
                "gv": _a_int(fila["away_score"]),
                "torneo": fila["tournament"].strip(),
                "pais": fila["country"].strip(),
                "neutral": fila["neutral"].strip().upper() == "TRUE",
            })
    return partidos


def _a_int(s):
    """Convierte un marcador a int; 'NA'/vacío -> None (partido sin jugar)."""
    s = (s or "").strip()
    if s == "" or s.upper() == "NA":
        return None
    try:
        return int(s)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Fixture y reconstrucción de grupos
# --------------------------------------------------------------------------

def extraer_fixture_wc(partidos):
    """Partidos del Mundial 2026 que aún no se han jugado (marcador NA)."""
    return [p for p in partidos
            if p["torneo"] == TORNEO_WC
            and p["fecha"].year == 2026
            and (p["gl"] is None or p["gv"] is None)]


def reconstruir_grupos(fixture):
    """
    Reconstruye los grupos con union-find: dos selecciones están en el mismo
    grupo si se enfrentan en la fase de grupos (round-robin). Las componentes
    conexas resultantes son los grupos. No se hardcodea ninguna composición.
    """
    padre = {}

    def find(x):
        padre.setdefault(x, x)
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    def union(a, b):
        padre[find(a)] = find(b)

    for p in fixture:
        union(p["local"], p["visitante"])

    grupos = defaultdict(set)
    for equipo in padre:
        grupos[find(equipo)].add(equipo)

    # Solo nos quedamos con componentes de 4 equipos (formato de grupos 2026).
    # Ordenamos los grupos por la fecha del primer partido y les ponemos letra.
    primer_partido = {}
    for p in fixture:
        raiz = find(p["local"])
        if raiz not in primer_partido or p["fecha"] < primer_partido[raiz]:
            primer_partido[raiz] = p["fecha"]

    raices_grupo = [r for r, eq in grupos.items() if len(eq) == 4]
    raices_grupo.sort(key=lambda r: primer_partido.get(r, date.max))

    etiqueta = {}
    for i, r in enumerate(raices_grupo):
        etiqueta[r] = "Grupo " + chr(ord("A") + i)

    # equipo -> letra de grupo
    grupo_de = {}
    for r in raices_grupo:
        for eq in grupos[r]:
            grupo_de[eq] = etiqueta[r]
    return grupo_de, find


# --------------------------------------------------------------------------
# Modelo: fuerza ofensiva / defensiva con recencia
# --------------------------------------------------------------------------

def peso_recencia(fecha):
    """Peso exponencial: partidos más recientes pesan más."""
    edad = (FECHA_REF - fecha).days
    return 0.5 ** (edad / VIDA_MEDIA_DIAS)


def calcular_fuerzas(partidos):
    """
    Estima la fuerza ofensiva y defensiva de cada selección con un ajuste
    iterativo tipo Dixon-Coles sobre los últimos 24 meses, ponderando por
    recencia. La clave (frente a un simple promedio de goles) es que TIENE EN
    CUENTA LA FUERZA DEL RIVAL: golear a un equipo débil suma menos que golear
    a uno fuerte. Devuelve (ataque, defensa, promedio_liga) donde:
      - ataque  > 1  -> marca más que el promedio
      - defensa > 1  -> recibe más que el promedio (peor defensa)
    """
    limite = VENTANA_DIAS
    relevantes = [
        p for p in partidos
        if p["gl"] is not None and p["gv"] is not None
        and 0 <= (FECHA_REF - p["fecha"]).days <= limite
    ]

    # Promedio de goles por equipo y partido (ponderado por recencia).
    suma_goles = suma_peso = 0.0
    equipos = set()
    muestras = []  # (peso, equipo, rival, goles_marcados, goles_recibidos)
    for p in relevantes:
        w = peso_recencia(p["fecha"])
        equipos.add(p["local"]); equipos.add(p["visitante"])
        muestras.append((w, p["local"], p["visitante"], p["gl"], p["gv"]))
        muestras.append((w, p["visitante"], p["local"], p["gv"], p["gl"]))
        suma_goles += w * (p["gl"] + p["gv"])
        suma_peso += 2 * w
    liga = suma_goles / suma_peso if suma_peso else 1.3

    # Pre-agrupamos las muestras por equipo para iterar rápido.
    por_equipo = defaultdict(list)
    for w, eq, riv, gf, gc in muestras:
        por_equipo[eq].append((w, riv, gf, gc))

    # Inicializamos todas las fuerzas en 1 (promedio) y refinamos por punto fijo.
    ataque = {e: 1.0 for e in equipos}
    defensa = {e: 1.0 for e in equipos}
    for _ in range(50):
        nuevo_at, nuevo_def = {}, {}
        for eq, juegos in por_equipo.items():
            # ataque = goles marcados / goles esperados si su ataque fuera medio.
            # Se añade un "prior" de PRIOR_PARTIDOS partidos contra rival medio
            # para regularizar a los equipos con pocos datos (shrink hacia 1).
            num_at = PRIOR_PARTIDOS * liga
            den_at = PRIOR_PARTIDOS * liga
            num_df = PRIOR_PARTIDOS * liga
            den_df = PRIOR_PARTIDOS * liga
            for w, riv, gf, gc in juegos:
                num_at += w * gf
                den_at += w * liga * defensa[riv]
                num_df += w * gc
                den_df += w * liga * ataque[riv]
            nuevo_at[eq] = num_at / den_at if den_at else 1.0
            nuevo_def[eq] = num_df / den_df if den_df else 1.0
        # Normalizamos para que el promedio de ataque y defensa sea ~1.
        ma = sum(nuevo_at.values()) / len(nuevo_at)
        md = sum(nuevo_def.values()) / len(nuevo_def)
        ataque = {e: v / ma for e, v in nuevo_at.items()}
        defensa = {e: v / md for e, v in nuevo_def.items()}
    return ataque, defensa, liga


# --------------------------------------------------------------------------
# Predicción por partido (Poisson)
# --------------------------------------------------------------------------

def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def predecir_partido(local, visitante, ataque, defensa, liga, hay_ventaja_local):
    """Devuelve dict con goles esperados, marcador más probable y probabilidades."""
    a_loc = ataque.get(local, 1.0)
    d_loc = defensa.get(local, 1.0)
    a_vis = ataque.get(visitante, 1.0)
    d_vis = defensa.get(visitante, 1.0)

    # Goles esperados: ataque propio * debilidad defensiva del rival * promedio.
    xg_loc = liga * a_loc * d_vis
    xg_vis = liga * a_vis * d_loc
    if hay_ventaja_local:
        xg_loc *= VENTAJA_LOCAL
        xg_vis /= (VENTAJA_LOCAL ** 0.5)

    # Rejilla de probabilidades conjuntas (independencia de Poisson).
    pl = [poisson_pmf(i, xg_loc) for i in range(MAX_GOLES + 1)]
    pv = [poisson_pmf(j, xg_vis) for j in range(MAX_GOLES + 1)]

    mejor_ij, mejor_p = (0, 0), -1.0
    p_local = p_empate = p_visit = 0.0
    for i in range(MAX_GOLES + 1):
        for j in range(MAX_GOLES + 1):
            pij = pl[i] * pv[j]
            if pij > mejor_p:
                mejor_p, mejor_ij = pij, (i, j)
            if i > j:
                p_local += pij
            elif i == j:
                p_empate += pij
            else:
                p_visit += pij

    total = p_local + p_empate + p_visit
    return {
        "xg_local": round(xg_loc, 2),
        "xg_visitante": round(xg_vis, 2),
        "marcador_local": mejor_ij[0],
        "marcador_visitante": mejor_ij[1],
        "prob_marcador": round(mejor_p * 100, 1),
        "prob_local": round(p_local / total * 100, 1),
        "prob_empate": round(p_empate / total * 100, 1),
        "prob_visitante": round(p_visit / total * 100, 1),
    }


# --------------------------------------------------------------------------
# Orquestación y salidas
# --------------------------------------------------------------------------

def generar(offline=False):
    ruta = descargar_datos(offline=offline)
    partidos = leer_partidos(ruta)
    print(f"Partidos leídos: {len(partidos)}")

    fixture = extraer_fixture_wc(partidos)
    print(f"Partidos del Mundial 2026 pendientes: {len(fixture)}")

    grupo_de, _ = reconstruir_grupos(fixture)
    ataque, defensa, liga = calcular_fuerzas(partidos)
    print(f"Promedio de goles por equipo/partido (24 meses): {liga:.3f}")

    # Predecimos solo partidos de fase de grupos (ambos equipos en el mismo grupo).
    predicciones = []
    for p in fixture:
        ga, gb = grupo_de.get(p["local"]), grupo_de.get(p["visitante"])
        if ga is None or gb is None or ga != gb:
            continue
        # Ventaja de local solo si el partido no es en cancha neutral.
        ventaja = not p["neutral"]
        pred = predecir_partido(p["local"], p["visitante"],
                                ataque, defensa, liga, ventaja)
        predicciones.append({
            "grupo": ga,
            "fecha": p["fecha"].isoformat(),
            "local": p["local"],
            "visitante": p["visitante"],
            "sede": p["pais"],
            **pred,
        })

    predicciones.sort(key=lambda x: (x["grupo"], x["fecha"], x["local"]))
    print(f"Predicciones de fase de grupos: {len(predicciones)}")

    _escribir_json(predicciones, liga)
    _escribir_texto(predicciones)
    _escribir_html(predicciones, liga)
    print("\nListo. Generados: data/predictions.json, predicciones.txt, index.html")


def _escribir_json(predicciones, liga):
    out = {
        "generado": FECHA_REF.isoformat(),
        "promedio_liga": round(liga, 3),
        "predicciones": predicciones,
    }
    with open(os.path.join(DIR_DATOS, "predictions.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


def _escribir_texto(predicciones):
    """Tabla de texto plano lista para copiar y enviar a la oficina."""
    lineas = []
    lineas.append("=" * 60)
    lineas.append("  PROYECCIÓN DE MARCADORES - FASE DE GRUPOS MUNDIAL 2026")
    lineas.append(f"  Generado: {FECHA_REF.isoformat()}  (estimación estadística)")
    lineas.append("=" * 60)
    grupo_actual = None
    for p in predicciones:
        if p["grupo"] != grupo_actual:
            grupo_actual = p["grupo"]
            lineas.append("")
            lineas.append(f"--- {grupo_actual} ---")
        marcador = f"{p['marcador_local']}-{p['marcador_visitante']}"
        linea = (f"  {p['fecha']}  {p['local']:>22}  {marcador:^5}  "
                 f"{p['visitante']:<22}  "
                 f"(L {p['prob_local']:.0f}% / E {p['prob_empate']:.0f}% / "
                 f"V {p['prob_visitante']:.0f}%)")
        lineas.append(linea)
    lineas.append("")
    lineas.append("Nota: marcador = resultado más probable según el modelo Poisson.")
    lineas.append("Es una estimación, no una certeza. ¡Suerte en la polla!")
    texto = "\n".join(lineas)
    with open(os.path.join(DIR_BASE, "predicciones.txt"), "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    print("\n" + texto)


def _escribir_html(predicciones, liga):
    """index.html standalone con los datos embebidos (abrir con doble clic)."""
    datos = json.dumps({"promedio_liga": round(liga, 3),
                        "generado": FECHA_REF.isoformat(),
                        "predicciones": predicciones},
                       ensure_ascii=False)
    html = _PLANTILLA_HTML.replace("/*__DATOS__*/", datos)
    with open(os.path.join(DIR_BASE, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


_PLANTILLA_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Predictor de Marcadores - Mundial 2026</title>
<style>
  :root { --bg:#0b132b; --card:#1c2541; --accent:#3a86ff; --good:#06d6a0;
          --warn:#ffd166; --text:#e8eef7; --muted:#9bb0cc; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background: linear-gradient(160deg,#0b132b,#1c2541); color: var(--text);
         padding: 24px; }
  h1 { font-size: 1.6rem; margin: 0 0 4px; }
  .sub { color: var(--muted); margin-bottom: 24px; font-size: .9rem; }
  .aviso { background: rgba(255,209,102,.12); border:1px solid var(--warn);
           color: var(--warn); padding:10px 14px; border-radius:10px;
           font-size:.85rem; margin-bottom:24px; }
  .grupos { display:grid; gap:18px; grid-template-columns: repeat(auto-fill,minmax(340px,1fr)); }
  .grupo { background: var(--card); border-radius:14px; padding:16px 16px 8px;
           box-shadow: 0 6px 18px rgba(0,0,0,.25); }
  .grupo h2 { font-size:1.05rem; margin:0 0 12px; color: var(--accent);
              border-bottom:1px solid rgba(255,255,255,.08); padding-bottom:8px; }
  .partido { padding:10px 0; border-bottom:1px solid rgba(255,255,255,.05); }
  .partido:last-child { border-bottom:none; }
  .fila { display:flex; align-items:center; gap:8px; }
  .eq { flex:1; }
  .eq.l { text-align:right; }
  .marc { font-weight:700; font-size:1.15rem; background:rgba(58,134,255,.18);
          padding:3px 10px; border-radius:8px; min-width:46px; text-align:center; }
  .meta { display:flex; justify-content:space-between; margin-top:6px;
          font-size:.72rem; color: var(--muted); }
  .barra { display:flex; height:6px; border-radius:4px; overflow:hidden; margin-top:6px; }
  .barra span { display:block; }
  .bL { background: var(--good); }
  .bE { background: var(--muted); }
  .bV { background: var(--accent); }
  .fecha { font-size:.7rem; color:var(--muted); margin-bottom:4px; }
  footer { margin-top:28px; color:var(--muted); font-size:.78rem; text-align:center; }
</style>
</head>
<body>
  <h1>⚽ Predictor de Marcadores — Mundial 2026</h1>
  <div class="sub" id="sub"></div>
  <div class="aviso">
    Estos marcadores son una <strong>estimación estadística</strong> basada en la
    forma reciente (últimos 24 meses) mediante un modelo de Poisson.
    No son una certeza: úsalos como guía para tu polla. 🍀
  </div>
  <div class="grupos" id="grupos"></div>
  <footer>Generado por predict.py · Datos: martj42/international_results</footer>

<script>
const DATA = /*__DATOS__*/;

const sub = document.getElementById("sub");
sub.textContent = `Fase de grupos · ${DATA.predicciones.length} partidos · `
  + `Generado ${DATA.generado}`;

// Agrupar por grupo
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
        <div class="fecha">${p.fecha} · ${p.sede}</div>
        <div class="fila">
          <span class="eq l">${p.local}</span>
          <span class="marc">${p.marcador_local}-${p.marcador_visitante}</span>
          <span class="eq">${p.visitante}</span>
        </div>
        <div class="barra">
          <span class="bL" style="width:${p.prob_local}%"></span>
          <span class="bE" style="width:${p.prob_empate}%"></span>
          <span class="bV" style="width:${p.prob_visitante}%"></span>
        </div>
        <div class="meta">
          <span>Gana local ${p.prob_local}%</span>
          <span>Empate ${p.prob_empate}%</span>
          <span>Gana visit. ${p.prob_visitante}%</span>
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
