#!/usr/bin/env python3
"""
Calendrier économique — protection automatique avant/après les grandes annonces.
Détecte FOMC, NFP, CPI, PCE, PIB, etc. et bloque les trades dans les fenêtres à risque.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

from kronos_model import _is_us_market_holiday

log = logging.getLogger("xtb_pw")

# ── Événements récurrents (patterns mensuels) ────────────────────────────────
# Format : (nom, description, impact, pattern_description)

HIGH_IMPACT_EVENTS = [
    # ── Fed / Politique monétaire ────────────────────────────────────────────
    ("FOMC_DECISION",     "Décision taux Fed",           "CRITIQUE",  "8 fois/an — 14h00 UTC"),
    ("FOMC_MINUTES",      "Minutes FOMC",                "TRES HAUT", "3 sem. après chaque FOMC"),
    ("FED_CHAIR_SPEECH",  "Discours Powell/Gouverneur",  "TRES HAUT", "Variable — Jackson Hole, Congrès"),
    ("JACKSON_HOLE",      "Symposium Jackson Hole",       "CRITIQUE",  "Fin août"),

    # ── Inflation ────────────────────────────────────────────────────────────
    ("CPI",               "Indice Prix Consommation US",  "CRITIQUE",  "2e mardi/mois — 12h30 UTC"),
    ("PPI",               "Indice Prix Producteurs US",   "HAUT",      "~2 jours après CPI"),
    ("PCE",               "PCE Core (indicateur Fed)",    "CRITIQUE",  "Dernier vendredi/mois"),
    ("ECB_CPI",           "CPI Zone Euro",                "HAUT",      "Mi-mois"),

    # ── Emploi ───────────────────────────────────────────────────────────────
    ("NFP",               "Non-Farm Payrolls",            "CRITIQUE",  "1er vendredi/mois — 12h30 UTC"),
    ("UNEMPLOYMENT",      "Taux chômage US",              "CRITIQUE",  "Avec NFP — 12h30 UTC"),
    ("JOBLESS_CLAIMS",    "Inscriptions chômage",         "MOYEN",     "Jeudi — 12h30 UTC"),
    ("ADP",               "ADP Employment",               "HAUT",      "Mercredi avant NFP — 12h15 UTC"),
    ("JOLTS",             "Offres emploi JOLTS",          "HAUT",      "Mi-mois"),

    # ── Croissance ───────────────────────────────────────────────────────────
    ("GDP_ADVANCE",       "PIB US (estimation avancée)",  "CRITIQUE",  "Fin janvier/avril/juillet/octobre"),
    ("GDP_FINAL",         "PIB US (final)",               "HAUT",      "3 semaines après avancée"),
    ("ISM_MFG",           "ISM Manufacturier",            "HAUT",      "1er jour ouvré/mois"),
    ("ISM_SERVICES",      "ISM Services",                 "HAUT",      "3e jour ouvré/mois"),

    # ── Banques centrales étrangères ─────────────────────────────────────────
    ("ECB_DECISION",      "Décision taux BCE",            "TRES HAUT", "6 semaines — 13h15 UTC"),
    ("BOE_DECISION",      "Décision taux BOE",            "TRES HAUT", "8 fois/an — 12h00 UTC"),
    ("BOJ_DECISION",      "Décision taux BOJ",            "HAUT",      "8 fois/an"),

    # ── Confiance & Consommation ─────────────────────────────────────────────
    ("CONSUMER_CONF",     "Confiance consommateur",       "MOYEN",     "Dernier mardi/mois"),
    ("RETAIL_SALES",      "Ventes au détail",             "HAUT",      "Mi-mois — 12h30 UTC"),

    # ── Immobilier ───────────────────────────────────────────────────────────
    ("EXISTING_HOME",     "Ventes maisons existantes",    "MOYEN",     "Mi-mois"),
    ("NEW_HOME",          "Ventes maisons neuves",        "MOYEN",     "Fin de mois"),
]

# Mots-clés pour détecter ces événements dans les news/recherches web
EVENT_KEYWORDS = {
    "FOMC":       ["fomc", "federal open market", "rate decision", "fed decision",
                   "interest rate", "powell statement", "fed hike", "fed cut"],
    "CPI":        ["cpi", "consumer price index", "inflation data", "inflation report",
                   "core cpi", "headline cpi"],
    "NFP":        ["nfp", "non-farm payroll", "jobs report", "employment report",
                   "payrolls", "nonfarm"],
    "PCE":        ["pce", "personal consumption expenditure", "core pce", "deflator"],
    "GDP":        ["gdp", "gross domestic product", "economic growth"],
    "ECB":        ["ecb", "european central bank", "lagarde", "bce"],
    "BOE":        ["boe", "bank of england", "bailey"],
    "BOJ":        ["boj", "bank of japan", "ueda", "kuroda"],
    "FED_SPEECH": ["powell", "fed governor", "fed president", "fomc member",
                   "waller", "jefferson", "williams", "daly", "kashkari",
                   "bostic", "barr", "cook", "kugler", "mester"],
    "JACKSON_HOLE": ["jackson hole", "economic symposium", "wyoming"],
}

# Fenêtres de protection (minutes avant et après l'annonce)
BLACKOUT_WINDOWS = {
    "CRITIQUE":  {"before": 60, "after": 90},   # FOMC, CPI, NFP
    "TRES HAUT": {"before": 45, "after": 60},
    "HAUT":      {"before": 30, "after": 45},
    "MOYEN":     {"before": 15, "after": 30},
}


@dataclass
class EconomicEvent:
    name: str
    description: str
    impact: str
    scheduled_time: datetime | None = None
    detected_from: str = ""          # "calendar" | "news" | "keyword"
    blackout_start: datetime | None = None
    blackout_end: datetime | None = None
    minutes_to_event: int | None = None


@dataclass
class CalendarStatus:
    is_blackout: bool = False
    active_events: list[EconomicEvent] = field(default_factory=list)
    upcoming_events: list[EconomicEvent] = field(default_factory=list)
    next_event_minutes: int | None = None
    risk_level: str = "NORMAL"       # "NORMAL" | "ELEVATED" | "BLACKOUT"
    message: str = ""
    cache_valid_until: float = 0.0


class EconomicCalendarEngine:
    """
    Moteur de calendrier économique.
    Détecte les fenêtres à risque et protège le capital avant les grandes annonces.
    """

    CACHE_TTL = 300  # 5 minutes

    # Événements récurrents par jour/heure UTC (approximatifs)
    RECURRING_UTC = {
        # (weekday, hour, minute) : (event_name, impact)
        # NFP : 1er vendredi du mois à 12h30 UTC
        # CPI : 2e mardi du mois à 12h30 UTC
        # FOMC : ~8 fois/an à 18h00 UTC (annonce) + 18h30 (conférence)
        # On ne peut pas prédire exactement sans calendrier externe
        # → On surveille via mots-clés dans les news
    }

    def __init__(self):
        self._cache: CalendarStatus | None = None
        self._known_events: list[EconomicEvent] = []

    def update_from_news_keywords(self, news_titles: list[str]) -> list[EconomicEvent]:
        """
        Détecte des événements économiques imminents dans les titres de news.
        Retourne une liste d'événements détectés.
        """
        detected = []
        now = datetime.now(timezone.utc)
        combined = " ".join(t.lower() for t in news_titles)

        for event_type, keywords in EVENT_KEYWORDS.items():
            if any(kw in combined for kw in keywords):
                # Chercher des indicateurs temporels
                time_indicators = [
                    "today", "tonight", "tomorrow", "this week",
                    "wednesday", "thursday", "friday",
                    "aujourd'hui", "demain", "cette semaine",
                    "imminent", "upcoming", "ahead", "preview",
                    "expected", "forecast", "consensus",
                ]
                is_imminent = any(ti in combined for ti in time_indicators)

                impact = "HAUT"
                if event_type in ("FOMC", "CPI", "NFP", "PCE", "GDP"):
                    impact = "CRITIQUE"
                elif event_type in ("ECB", "BOE", "FED_SPEECH"):
                    impact = "TRES HAUT"

                ev = EconomicEvent(
                    name=event_type,
                    description=next(
                        (e[1] for e in HIGH_IMPACT_EVENTS if event_type in e[0]),
                        event_type
                    ),
                    impact=impact,
                    detected_from="news_keyword",
                    minutes_to_event=0 if is_imminent else None,
                )

                if is_imminent:
                    windows = BLACKOUT_WINDOWS.get(impact, BLACKOUT_WINDOWS["HAUT"])
                    ev.blackout_start = now - timedelta(minutes=windows["before"])
                    ev.blackout_end   = now + timedelta(minutes=windows["after"])

                detected.append(ev)

        return detected

    def check_standard_blackouts(self) -> list[EconomicEvent]:
        """
        Vérifie les fenêtres de blackout standard basées sur l'heure UTC.
        NFP : 1er vendredi du mois 12h00–14h00 UTC
        CPI : 2e mardi du mois 12h00–13h30 UTC
        FOMC : Mercredis FOMC à 17h30–20h00 UTC (estimation)
        """
        now      = datetime.now(timezone.utc)
        weekday  = now.weekday()  # 0=Lundi, 4=Vendredi
        hour     = now.hour
        minute   = now.minute
        day      = now.day
        blackouts = []

        # NFP : Vendredi 12h00–14h30 UTC, 1er-7e jour du mois
        # Décalé au jeudi si ce vendredi est un jour férié NYSE observé
        if weekday == 4 and 1 <= day <= 7 and 12 <= hour <= 14 and not _is_us_market_holiday(now.date()):
            blackouts.append(EconomicEvent(
                name="NFP",
                description="Non-Farm Payrolls — HAUTE VOLATILITE",
                impact="CRITIQUE",
                detected_from="time_pattern",
            ))
        # NFP décalé : jeudi si le vendredi ≤7 est férié NYSE
        if weekday == 3 and 1 <= day <= 7 and 12 <= hour <= 14:
            next_day = now.date() + timedelta(days=1)
            if next_day.day <= 7 and _is_us_market_holiday(next_day):
                blackouts.append(EconomicEvent(
                    name="NFP",
                    description="Non-Farm Payrolls (avancé — vendredi férié) — HAUTE VOLATILITE",
                    impact="CRITIQUE",
                    detected_from="time_pattern",
                ))

        # CPI : Mardi 12h00–13h30 UTC, 8e-15e jour du mois
        if weekday == 1 and 8 <= day <= 15 and 12 <= hour <= 13:
            blackouts.append(EconomicEvent(
                name="CPI",
                description="CPI Release — HAUTE VOLATILITE",
                impact="CRITIQUE",
                detected_from="time_pattern",
            ))

        # FOMC : Mercredi à 17h30–20h30 UTC (annonce + conférence)
        # Les FOMC ont lieu ~8 fois/an, on applique une protection large
        if weekday == 2 and 17 <= hour <= 20:
            blackouts.append(EconomicEvent(
                name="FOMC_POTENTIAL",
                description="Fenêtre FOMC potentielle — vérifier calendrier",
                impact="TRES HAUT",
                detected_from="time_pattern",
            ))

        # PCE : Dernier vendredi du mois 12h30 UTC
        if weekday == 4 and day >= 25 and hour == 12 and 20 <= minute <= 59:
            blackouts.append(EconomicEvent(
                name="PCE",
                description="PCE Core Release",
                impact="CRITIQUE",
                detected_from="time_pattern",
            ))

        # Jobless Claims : Jeudi 12h30 UTC
        if weekday == 3 and hour == 12 and 20 <= minute <= 59:
            blackouts.append(EconomicEvent(
                name="JOBLESS_CLAIMS",
                description="Inscriptions chômage hebdomadaires",
                impact="MOYEN",
                detected_from="time_pattern",
            ))

        return blackouts

    def assess(self, news_titles: list[str] | None = None) -> CalendarStatus:
        """Évaluation complète du risque calendrier."""
        now = time.monotonic()

        if self._cache and now < self._cache.cache_valid_until:
            return self._cache

        status = CalendarStatus()
        status.cache_valid_until = now + self.CACHE_TTL

        # 1. Blackouts basés sur l'heure
        time_events = self.check_standard_blackouts()
        status.active_events.extend(time_events)

        # 2. Événements détectés dans les news
        if news_titles:
            news_events = self.update_from_news_keywords(news_titles)
            for ev in news_events:
                if ev.minutes_to_event == 0:  # imminents
                    status.active_events.append(ev)
                else:
                    status.upcoming_events.append(ev)

        # 3. Classification du risque
        if any(e.impact == "CRITIQUE" for e in status.active_events):
            status.is_blackout  = True
            status.risk_level   = "BLACKOUT"
            names = [e.name for e in status.active_events if e.impact == "CRITIQUE"]
            status.message = f"BLACKOUT ACTIF — {', '.join(names)} — trades suspendus"

        elif any(e.impact in ("TRES HAUT", "HAUT") for e in status.active_events):
            status.is_blackout  = True
            status.risk_level   = "ELEVATED"
            names = [e.name for e in status.active_events]
            status.message = f"RISQUE ELEVE — {', '.join(names)} — position réduite"

        elif status.upcoming_events:
            status.risk_level = "ELEVATED"
            status.message    = f"Evenements imminents: {', '.join(e.name for e in status.upcoming_events[:3])}"

        else:
            status.risk_level = "NORMAL"
            status.message    = "Aucun événement critique détecté"

        self._cache = status
        return status

    def print_status(self, status: CalendarStatus):
        if status.risk_level == "BLACKOUT":
            log.warning(f"  [CALENDRIER] {status.message}")
        elif status.risk_level == "ELEVATED":
            log.info(f"  [CALENDRIER] {status.message}")
        else:
            log.info(f"  [CALENDRIER] {status.message}")

        for ev in status.upcoming_events[:3]:
            log.info(f"    >> A venir: {ev.name} — {ev.description}")
