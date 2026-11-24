import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

URL = "https://rem.info/fr/se-deplacer/etat-du-service"
OUTPUT_PATH = Path("rem_status.json")
STATION_FOCUS = "Canora"

# Liste des stations du réseau REM
STATIONS_REM = [
    "Brossard",
    "Du Quartier",
    "Panama",
    "Île-des-Sœurs",
    "Gare Centrale",
    "McGill",
    "Édouard-Montpetit",
    "Canora",
    "Ville-de-Mont-Royal",
    "Côte-de-Liesse",
    "Montpellier",
    "Du Ruisseau",
    "Bois-Franc",
    "Sunnybrooke",
    "Pierrefonds-Roxboro",
    "Île-Bigras",
    "Sainte-Dorothée",
    "Grand-Moulin",
    "Deux-Montagnes",
    "Marie-Curie",
    "YUL-Aéroport-Montréal-Trudeau",
    "Anse-à-l'Orme",
    "Kirkland",
    "Fairview-Pointe-Claire",
    "Des Sources",
]


def normalize_str(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower()


def extract_full_status() -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="fr-CA")
        page.goto(URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        lines = [
            re.sub(r"\s+", " ", line).strip()
            for line in page.inner_text("body").splitlines()
            if re.sub(r"\s+", " ", line).strip()
        ]
        browser.close()

    stations_data = {
        s: {"niveau": "normal", "statut": "Service normal", "alertes": []}
        for s in STATIONS_REM
    }
    alertes_globales: list[str] = []

    mots_cles_reseau = (
        "interruption",
        "ralentissement",
        "arrêt de service",
        "non desservie",
        "fermée",
    )

    for idx, line in enumerate(lines):
        low = normalize_str(line)
        if "a venir" in low or "planifie" in low:
            continue

        window = " — ".join(lines[idx : min(idx + 3, len(lines))])
        window_norm = normalize_str(window)

        is_elevator = "ascenseur" in window_norm and (
            "hors service" in window_norm or "panne" in window_norm
        )
        is_service = any(k in low for k in mots_cles_reseau)

        if not (is_elevator or is_service):
            continue

        matched_station = False
        for station in STATIONS_REM:
            st_norm = normalize_str(station)
            if re.search(rf"\b{re.escape(st_norm)}\b", window_norm):
                matched_station = True
                entry = stations_data[station]
                if window not in entry["alertes"]:
                    entry["alertes"].append(window)

                if is_service:
                    entry["niveau"] = "alerte"
                    entry["statut"] = "Alerte service"
                elif is_elevator and entry["niveau"] != "alerte":
                    entry["niveau"] = "avertissement"
                    entry["statut"] = "Ascenseur HS"

        if not matched_station and is_service and any(
            expr in window_norm for expr in ("ensemble du reseau", "toutes les stations")
        ):
            if window not in alertes_globales:
                alertes_globales.append(window)

    # Si une alerte globale touche tout le réseau, elle s'applique à toutes les stations
    if alertes_globales:
        for station in STATIONS_REM:
            stations_data[station]["niveau"] = "alerte"
            stations_data[station]["statut"] = "Alerte réseau"
            stations_data[station]["alertes"].extend(
                a for a in alertes_globales if a not in stations_data[station]["alertes"]
            )

    # Résumé optimisé pour KWGT (centré sur Canora + compteur réseau)
    focus = stations_data[STATION_FOCUS]
    autres_stations_alerte = [
        s for s, info in stations_data.items() if s != STATION_FOCUS and info["niveau"] != "normal"
    ]

    if focus["niveau"] == "alerte":
        kwgt_titre = f"{STATION_FOCUS} : Alerte"
        kwgt_detail = focus["alertes"][0][:140]
    elif focus["niveau"] == "avertissement":
        kwgt_titre = f"{STATION_FOCUS} : Ascenseur HS"
        kwgt_detail = focus["alertes"][0][:140]
    else:
        kwgt_titre = f"{STATION_FOCUS} {statut_focus}"
