#!/usr/bin/env python3
"""Actualiza el directorio FIL 2026 desde las listas oficiales r=6 y r=13.

Uso desde la raíz del repositorio: python scripts/actualizar_fil.py
No requiere paquetes externos. Solo escribe index.html cuando las dos fuentes
se descargaron y procesaron con éxito.
"""
from __future__ import annotations
import datetime as dt
import html
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "index.html"
YEAR = 2026
URLS = {
    "Evento": "https://www.fil.com.mx/prog/resultados.asp?r=6&idsr=0&f=0&e=2026&ids=0",
    "Firma": "https://www.fil.com.mx/prog/resultados.asp?r=13&idsr=0&f=0&e=2026&ids=0",
}
MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
          "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
          "octubre": 10, "noviembre": 11, "diciembre": 12}


def text(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(fragment)).strip()


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "FIL-Autores-directory/1.0 (daily update)"})
    with urllib.request.urlopen(request, timeout=40) as response:
        charset = response.headers.get_content_charset() or "windows-1252"
        return response.read().decode(charset, errors="replace")


def date_iso(value: str) -> str:
    found = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)", value, re.I)
    if not found:
        return ""
    month = MONTHS.get(found.group(2).lower())
    return f"{YEAR}-{month:02d}-{int(found.group(1)):02d}" if month else ""


def page_records(source_url: str, kind: str) -> tuple[list[dict], int]:
    records, page, seen = [], 1, set()
    while page <= 100:
        url = source_url if page == 1 else source_url + f"&pg={page}"
        if url in seen:
            raise RuntimeError("La paginación repitió una URL.")
        seen.add(url)
        raw = fetch(url)
        cards = re.split(r'<div\s+class="card">', raw, flags=re.I)[1:]
        if not cards:
            raise RuntimeError(f"No se encontraron fichas en {kind}, página {page}.")
        for card in cards:
            title_match = re.search(r"<h3[^>]*>(.*?)</h3>", card, re.I | re.S)
            author_match = re.search(r"<strong[^>]*>Autor(?:a|es)?\s*:\s*</strong>(.*?)(?:</p>|<br)", card, re.I | re.S)
            date_match = re.search(r'class="ms-1 mb-0">([^<]+)<br\s*/?>\s*([^<]+)</p>', card, re.I)
            venue_match = re.search(r"bi-geo-alt[\s\S]*?<p[^>]*>\s*<a[^>]*>(.*?)</a>", card, re.I)
            if not (title_match and author_match and date_match):
                continue
            title, authors = text(title_match.group(1)), text(author_match.group(1))
            when, hours = text(date_match.group(1)), text(date_match.group(2))
            date = date_iso(when)
            if not title or not authors or not date:
                continue
            editorial_match = re.search(r"<b[^>]*>Editorial:\s*</b>(.*?)</p>", card, re.I | re.S)
            activity = {"k": kind, "t": title, "d": date, "h": hours,
                        "e": text(editorial_match.group(1)) if editorial_match else "",
                        "l": text(venue_match.group(1)) if venue_match else ""}
            if "prerregistro" in card.lower(): activity["pr"] = True
            if "lugares agotados" in card.lower(): activity["sold"] = True
            # En estas listas, cada ficha asigna una autoría explícita. "Varios" no se atribuye.
            if authors.lower() in {"varios", "varias", "autoría: varios"}:
                continue
            records.append((authors, activity))
        if not re.search(r'href="[^"]*pg=\d+[^"]*"[^>]*>\s*Siguiente', raw, re.I):
            return records, page
        page += 1
    raise RuntimeError(f"La paginación de {kind} superó 100 páginas.")


def main() -> int:
    if not OUTPUT.is_file():
        print("Falta index.html en la raíz del repositorio. Coloca ahí la página antes de ejecutar.", file=sys.stderr)
        return 2
    template = OUTPUT.read_text(encoding="utf-8")
    if not re.search(r"const DATA=\[.*?\];", template, re.S):
        print("No se encontró el bloque de datos const DATA en index.html; no se modificó el archivo.", file=sys.stderr)
        return 2
    try:
        events, event_pages = page_records(URLS["Evento"], "Evento")
        signings, signing_pages = page_records(URLS["Firma"], "Firma")
    except (urllib.error.URLError, TimeoutError, RuntimeError, UnicodeError) as exc:
        print(f"No se pudo completar la consulta ({exc}). index.html quedó intacto.", file=sys.stderr)
        return 1
    people: dict[str, dict] = {}
    for author, activity in events + signings:
        person = people.setdefault(author, {"n": author, "a": []})
        if activity not in person["a"]:
            person["a"].append(activity)
    data = sorted(people.values(), key=lambda item: item["n"].casefold())
    if not data:
        print("Las fuentes no devolvieron autores identificables; no se modificó index.html.", file=sys.stderr)
        return 1
    activities = sum(len(person["a"]) for person in data)
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    updated = re.sub(r"const DATA=\[.*?\];", "const DATA=" + encoded + ";", template, count=1, flags=re.S)
    today = dt.date.today().strftime("%-d de %B de %Y") if sys.platform != "win32" else f"{dt.date.today().day} de {['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'][dt.date.today().month-1]} de {dt.date.today().year}"
    updated = re.sub(r"Actualizado al [^<]*:</b>.*?</div>",
                     f"Actualizado al {today}:</b> {len(data)} autores y {activities} eventos.</div>", updated, count=1, flags=re.S)
    temp = OUTPUT.with_suffix(".html.tmp")
    temp.write_text(updated, encoding="utf-8")
    temp.replace(OUTPUT)
    print(f"Actualizado: {len(data)} autores, {activities} actividades.")
    print(f"Páginas recorridas: r=6: {event_pages}; r=13: {signing_pages}.")
    print(f"Archivo: {OUTPUT}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
