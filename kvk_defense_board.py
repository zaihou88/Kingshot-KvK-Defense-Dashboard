"""
KvK Defense Board — Streamlit / Python port

A self-hosted alternative to the Claude-artifact version of the same tool.
Run locally with:  streamlit run kvk_defense_board.py
Data is stored in a local SQLite file (kvk_board.db) next to this script,
shared by everyone who opens the running app.

Officer access is hidden from the tab bar unless you open this app with
?officer=1 on the end of the URL (e.g. https://your-app.streamlit.app/?officer=1).

Tunable settings (troop stat weights, default structures, default
passcodes) live in config.py, not this file — edit that one instead.
"""

import json
import re
import time
import base64
from html import escape as _esc
from pathlib import Path

import pandas as pd
import streamlit as st
import sqlite3

from config import (
    DB_PATH,
    STAT_TYPES,
    STAT_FIELDS,
    TIER_OPTIONS,
    TYPE_MARK,
    STAT_WEIGHTS,
    STAT_TOTAL_WEIGHT,
    DEFAULT_STATE,
)
from battle_plan_image import render_structure_card, render_full_plan

# Short column headers for the bulk-entry stat grid (e.g. "Inf LETH").
TYPE_ABBR = {"Infantry": "Inf", "Cavalry": "Cav", "Archer": "Arc"}
FIELD_ABBR = {"Attack": "ATK", "Defense": "DEF", "Lethality": "LETH", "Health": "HP"}


# ---------- storage ----------

@st.cache_resource
def get_conn():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS players (id TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    return conn


def load_state():
    conn = get_conn()
    row = conn.execute("SELECT value FROM config WHERE key='board'").fetchone()
    if row:
        state = dict(DEFAULT_STATE)
        state.update(json.loads(row[0]))
        return state
    save_state(DEFAULT_STATE)
    return dict(DEFAULT_STATE)


def save_state(state):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('board', ?)", (json.dumps(state),))
    conn.commit()


def load_published_plan():
    conn = get_conn()
    row = conn.execute("SELECT value FROM config WHERE key='published_plan'").fetchone()
    return json.loads(row[0]) if row else None


def save_published_plan(plan):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('published_plan', ?)", (json.dumps(plan),))
    conn.commit()


def load_players():
    conn = get_conn()
    rows = conn.execute("SELECT value FROM players").fetchall()
    return [json.loads(r[0]) for r in rows]


def upsert_player(entry):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO players (id, value) VALUES (?, ?)", (entry["id"], json.dumps(entry)))
    conn.commit()


def delete_player(player_id):
    conn = get_conn()
    conn.execute("DELETE FROM players WHERE id = ?", (player_id,))
    conn.commit()


# ---------- helpers ----------

def tier_num(t):
    m = re.search(r"\d+", str(t))
    return int(m.group()) if m else 1


def fmt(n):
    n = n or 0
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "player"


ICON_DIR = Path(__file__).parent / "icons"


@st.cache_data
def _load_icon_b64(filename):
    """Base64-encodes a bundled icon for inline <img> embedding. Returns None
    (falling back to an emoji elsewhere) if the icons/ folder wasn't uploaded
    alongside this file — same defensive pattern as the bundled fonts."""
    try:
        return base64.b64encode((ICON_DIR / filename).read_bytes()).decode("utf-8")
    except OSError:
        return None


CASTLE_ICON_B64 = _load_icon_b64("castle.png")
TURRET_ICON_B64 = _load_icon_b64("turret.png")
LOGO_ICON_B64 = _load_icon_b64("logo.png")


def structure_icon_html(is_castle, size=26):
    b64 = CASTLE_ICON_B64 if is_castle else TURRET_ICON_B64
    if not b64:
        return "🏰" if is_castle else "🗼"
    return (
        f'<img src="data:image/png;base64,{b64}" '
        f'style="width:{size}px;height:{size}px;vertical-align:middle;border-radius:4px;">'
    )


def render_header(kingdom_name):
    """Logo + title + credit line, used identically on the passcode gate and the main app.
    Fixed (not sticky — Streamlit's own toolbar sits at a high z-index that sticky
    positioning couldn't get above, so this pins below it instead) so officers don't
    lose kingdom context scrolling through a long roster. Reverts to normal static
    flow below 640px — a wrapped multi-line title makes a fixed height impossible to
    predict correctly, and it would otherwise cover the tabs on a narrow phone."""
    logo_html = ""
    if LOGO_ICON_B64:
        logo_html = (
            f'<img src="data:image/png;base64,{LOGO_ICON_B64}" '
            f'class="kvk-header-logo" style="height:38px;vertical-align:middle;margin-right:14px;">'
        )
    st.markdown(
        f'<div class="kvk-fixed-header" style="position:fixed;top:60px;left:0;right:0;z-index:999;background:#262B34;'
        f'padding:14px 3.5rem 8px 3.5rem;border-bottom:1px solid #333A45;">'
        f'<div style="display:flex;align-items:center;gap:0;margin-bottom:2px;">'
        f'{logo_html}'
        f'<span class="kvk-header-title" style="font-family:\'Oswald\',sans-serif;font-size:2rem;font-weight:600;color:#EDEEF2;">'
        f'{_esc(kingdom_name)} — KvK Defense Board</span>'
        f'</div>'
        f'<div style="font-size:11px;color:#9BA5B2;">Created with Claude AI and Takara</div>'
        f'</div>'
        f'<div class="kvk-header-spacer" style="height:100px;"></div>',
        unsafe_allow_html=True,
    )


def compute_assign_label(state, player_id):
    """The current Assign-column value for one player: their override structure
    name, 'Reserve', or 'Auto' if unassigned. Shared by the desktop table and
    mobile card rendering so they can't drift out of sync."""
    ov = state["overrides"].get(player_id)
    if ov == "reserve":
        return "Reserve"
    match = next((s["name"] for s in state["structures"] if s["id"] == ov), None)
    return match or "Auto"


def parse_uploaded_bulk_file(uploaded_file, expected_columns, numeric_columns, tier_options, castle_options):
    """Parse an uploaded CSV/Excel into a DataFrame matching expected_columns.
    Returns (df, warnings) on success, or (None, [error]) if it can't be used."""
    warnings = []
    try:
        name_lower = uploaded_file.name.lower()
        if name_lower.endswith((".xlsx", ".xls")):
            raw = pd.read_excel(uploaded_file)
        else:
            raw = pd.read_csv(uploaded_file)
    except Exception as e:
        return None, [f"Couldn't read that file: {e}"]

    raw.columns = [str(c).strip() for c in raw.columns]
    missing = [c for c in expected_columns if c not in raw.columns]
    if missing:
        return None, [
            f"Missing column(s): {', '.join(missing)}. Download the template above to see the exact format needed."
        ]

    df = raw[expected_columns].copy()

    for col in numeric_columns:
        df[col] = df[col].astype(str).str.replace(",", "", regex=False).str.strip()
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["Tier"] = df["Tier"].astype(str).str.strip()
    bad_tier = ~df["Tier"].isin(tier_options)
    if bad_tier.any():
        warnings.append(f"{int(bad_tier.sum())} row(s) had an unrecognized Tier — set to T1.")
        df.loc[bad_tier, "Tier"] = "T1"

    df["Castle"] = df["Castle"].astype(str).str.strip()
    bad_castle = ~df["Castle"].isin(castle_options)
    if bad_castle.any():
        warnings.append(f"{int(bad_castle.sum())} row(s) had an unrecognized Castle level — set to 1.")
        df.loc[bad_castle, "Castle"] = "1"

    df = df[~df["Name"].isna()]
    df["Name"] = df["Name"].astype(str).str.strip()
    if "Alliance" in df.columns:
        df["Alliance"] = df["Alliance"].fillna("").astype(str).str.strip()

    df = df[df["Name"] != ""].reset_index(drop=True)
    if df.empty:
        return None, ["No rows with a Name found in that file."]
    return df, warnings


def derive_type(stats):
    if not stats:
        return None
    best, best_score = None, 0
    for t in STAT_TYPES:
        s = stats.get(t, {})
        score = sum(float(s.get(f, 0) or 0) for f in STAT_FIELDS)
        if score > best_score:
            best_score, best = score, t
    return best


def stats_avg(stats):
    if not stats:
        return 0
    total = 0
    for t in STAT_TYPES:
        for f in STAT_FIELDS:
            total += float(stats.get(t, {}).get(f, 0) or 0) * STAT_WEIGHTS[t][f]
    return total / STAT_TOTAL_WEIGHT


def castle_level_options(max_tg):
    tg = max(1, int(max_tg or 8))
    levels = [str(i) for i in range(1, 31)]
    grades = [f"TG{i}" for i in range(1, tg + 1)]
    return levels + grades


def castle_level_rank(level):
    if not level:
        return 0
    s = str(level)
    if s.startswith("TG"):
        try:
            return 30 + int(s[2:])
        except ValueError:
            return 30
    try:
        return int(s)
    except ValueError:
        return 0


def leader_key(p):
    return (-p["statsAvg"], -p.get("rally", 0), -tier_num(p["tier"]), -castle_level_rank(p.get("castleLevel")), -p.get("power", 0))


def joiner_key(p):
    return (-tier_num(p["tier"]), -castle_level_rank(p.get("castleLevel")), -p.get("march", 0))


def assign(raw_players, structures, overrides):
    """Leader-first assignment: pick leaders globally by stats > rally > tier+castle level > power,
    then their rally size becomes that tower's real capacity. Joiners fill by tier+castle level
    then march size, matching each tower's Infantry/Cavalry/Archer ratio where possible."""
    players = []
    for p in raw_players:
        pp = dict(p)
        pp["type"] = derive_type(p.get("stats"))
        pp["statsAvg"] = stats_avg(p.get("stats"))
        players.append(pp)

    ordered = sorted(structures, key=lambda s: 0 if s["kind"] == "castle" else 1)

    overridden_ids = {pid for pid, v in overrides.items() if v and v != "reserve"}
    reserved_ids = {pid for pid, v in overrides.items() if v == "reserve"}
    eligible = [p for p in players if p.get("rally", 0) > 0 and p["id"] not in reserved_ids and p["id"] not in overridden_ids]
    eligible.sort(key=leader_key)

    leaders = {}
    backup_leaders = {}
    used_leader_ids = set()
    for s in ordered:
        pick = next((p for p in eligible if p["id"] not in used_leader_ids), None)
        leaders[s["id"]] = pick
        if pick:
            used_leader_ids.add(pick["id"])
    for s in ordered:
        pick = next((p for p in eligible if p["id"] not in used_leader_ids), None)
        backup_leaders[s["id"]] = pick
        if pick:
            used_leader_ids.add(pick["id"])

    capacities = {}
    for s in ordered:
        leader = leaders[s["id"]]
        capacities[s["id"]] = leader["rally"] if leader else s["capacity"]

    remaining, type_remaining = {}, {}
    for s in ordered:
        cap = capacities[s["id"]]
        remaining[s["id"]] = cap
        type_remaining[s["id"]] = {t: cap * (s["ratio"].get(t, 0) / 100) for t in STAT_TYPES}

    assignments = {s["id"]: [] for s in ordered}
    reserve = []
    manually_placed = set()

    for s in ordered:
        leader = leaders[s["id"]]
        if leader:
            assignments[s["id"]].append(leader)
            remaining[s["id"]] -= leader["march"]
            if leader.get("type"):
                type_remaining[s["id"]][leader["type"]] -= leader["march"]
            manually_placed.add(leader["id"])
        backup = backup_leaders[s["id"]]
        if backup and remaining[s["id"]] >= backup["march"]:
            assignments[s["id"]].append(backup)
            remaining[s["id"]] -= backup["march"]
            if backup.get("type"):
                type_remaining[s["id"]][backup["type"]] -= backup["march"]
            manually_placed.add(backup["id"])

    for p in players:
        if p["id"] in manually_placed:
            continue
        ov = overrides.get(p["id"])
        if ov and ov != "reserve" and ov in remaining:
            assignments[ov].append(p)
            remaining[ov] -= p["march"]
            if p.get("type"):
                type_remaining[ov][p["type"]] -= p["march"]
            manually_placed.add(p["id"])
        elif ov == "reserve":
            manually_placed.add(p["id"])
            reserve.append(p)

    pool = sorted((p for p in players if p["id"] not in manually_placed), key=joiner_key)
    unplaced = []
    for p in pool:
        placed = False
        if p.get("type"):
            for s in ordered:
                tr = type_remaining[s["id"]]
                if remaining[s["id"]] >= p["march"] and tr[p["type"]] >= p["march"]:
                    assignments[s["id"]].append(p)
                    remaining[s["id"]] -= p["march"]
                    tr[p["type"]] -= p["march"]
                    placed = True
                    break
        if not placed:
            unplaced.append(p)

    still_unplaced = []
    for p in unplaced:
        placed = False
        for s in ordered:
            if remaining[s["id"]] >= p["march"]:
                assignments[s["id"]].append(p)
                remaining[s["id"]] -= p["march"]
                placed = True
                break
        if not placed:
            still_unplaced.append(p)
    reserve.extend(still_unplaced)

    return assignments, reserve, remaining, leaders, capacities, backup_leaders


# ---------- app ----------

st.set_page_config(page_title="KvK Defense Board", layout="wide")

# Custom styling — a restrained, "modern dashboard" look: one true accent
# color reserved for primary actions only, quiet outline buttons for
# everything else, underline-style tabs, and a cooler off-white that
# actually pairs with a violet accent instead of fighting it.
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Oswald:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&family=Barlow:wght@400;500;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Barlow', sans-serif;
    }
    .stApp {
        background-color: #262B34;
        color: #EDEEF2;
    }
    [data-testid="stHeader"] {
        background-color: #262B34;
    }
    h1, h2, h3 {
        font-family: 'Oswald', sans-serif !important;
        letter-spacing: 0.2px;
    }
    h1 { color: #EDEEF2 !important; }

    /* Panels — containers, expanders, forms. stLayoutWrapper is Streamlit's
       generic layout testid — it wraps EVERY layout block (tab panels,
       columns, st.container alike), not just intentional bordered cards, so
       styling it unconditionally paints a card background behind things like
       the whole tab panel too. Requiring it to be nested inside another
       wrapper targets only genuinely-nested containers (an intentional
       st.container sitting inside a column inside a tab) and leaves the
       outermost per-tab wrapper transparent. */
    [data-testid="stLayoutWrapper"] [data-testid="stLayoutWrapper"],
    [data-testid="stExpander"],
    [data-testid="stForm"] {
        background-color: #3E4654 !important;
        border: 1px solid #55606F !important;
        border-radius: 8px !important;
    }

    /* Expander header — the clickable summary bar is a separate element
       from the expander body and needs its own background/text override,
       or it falls back to a bright default that's unreadable until hover. */
    [data-testid="stExpander"] summary {
        background-color: #3E4654 !important;
        border-radius: 8px !important;
    }
    [data-testid="stExpander"] summary:hover {
        background-color: #333A45 !important;
    }
    [data-testid="stExpander"] summary p,
    [data-testid="stExpander"] summary span {
        color: #EDEEF2 !important;
    }
    [data-testid="stExpander"] summary svg {
        fill: #EDEEF2 !important;
    }

    /* Tighter vertical rhythm — denser, more like a dashboard than a
       typical spaced-out web form. */
    [data-testid="stVerticalBlock"] {
        gap: 0.4rem !important;
    }
    [data-testid="stLayoutWrapper"] {
        padding: 10px 14px !important;
    }
    [data-testid="element-container"] {
        margin-bottom: 0 !important;
    }

    /* Primary buttons — the one accent-filled action per view: Publish,
       Submit, Apply, Enter. Everything else stays a quiet outline button
       (below) so the important action actually stands out. Form submit
       buttons get a DIFFERENT testid suffix (primaryFormSubmit, not just
       primary) — this was silently missing that variant, meaning "Submit
       stats" and both passcode "Enter" buttons had zero CSS fallback and
       depended entirely on theme.toml loading. */
    [data-testid="stBaseButton-primary"],
    [data-testid="stBaseButton-primaryFormSubmit"] {
        background-color: #F0B02E !important;
        color: #262B34 !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600;
    }
    [data-testid="stBaseButton-primary"]:hover,
    [data-testid="stBaseButton-primaryFormSubmit"]:hover {
        background-color: #F5C158 !important;
        color: #262B34 !important;
    }

    /* Secondary / utility buttons — outline style, not competing with
       the primary action for attention. */
    [data-testid="stBaseButton-secondary"],
    [data-testid="stBaseButton-secondaryFormSubmit"] {
        background-color: transparent !important;
        color: #C3CAD2 !important;
        border: 1px solid #55606F !important;
        border-radius: 8px !important;
        font-weight: 500;
    }
    [data-testid="stBaseButton-secondary"]:hover,
    [data-testid="stBaseButton-secondaryFormSubmit"]:hover {
        background-color: #333A45 !important;
        border-color: #6B7684 !important;
        color: #EDEEF2 !important;
    }

    /* Text / number / password inputs, selects */
    input, textarea,
    [data-baseweb="select"] > div,
    [data-baseweb="input"] {
        background-color: #262B34 !important;
        color: #EDEEF2 !important;
        border: 1px solid #55606F !important;
        border-radius: 8px !important;
    }

    /* Tabs — pill-style segmented control: a rounded track housing pill
       buttons, active tab gets a solid fill. Matches "Navigation = Blue"
       from the Kingshot palette guide. Tabs render as <div role="tab">, not
       <button>, in this Streamlit version — data-testid is the stable
       selector, not the emotion-generated class names. */
    [data-testid="stTabs"] [role="tablist"] {
        display: flex;
        width: 100%;
        gap: 6px;
        background: #262B34;
        border-bottom: none;
        border-radius: 10px;
        padding: 5px;
    }
    [data-testid="stTabs"] [data-testid="stTab"] {
        flex: 1 1 0;
        justify-content: center;
        background-color: transparent;
        color: #9BA5B2;
        border-radius: 8px !important;
        border-bottom: none;
        font-family: 'Barlow', sans-serif;
        font-weight: 500;
        padding: 8px 14px;
        cursor: pointer;
    }
    [data-testid="stTabs"] [data-testid="stTab"] p {
        color: #9BA5B2 !important;
        font-weight: 500 !important;
    }
    [data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] {
        background-color: #2D5DA8;
        color: #F8FAFC !important;
        border-bottom: none;
        font-weight: 600;
    }
    [data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] p {
        color: #F8FAFC !important;
        font-weight: 600 !important;
    }
    /* Streamlit renders its own active-tab indicator bar (using theme.primaryColor,
       our gold) as an absolutely-positioned last child inside each tab — invisible
       until active, but redundant and clashing once our pill fill already shows
       which tab is selected. Neutralize its color rather than display:none, since
       Streamlit's own JS sizes/positions it and hiding it outright risks layout
       shift on tab switch. */
    [data-testid="stTabs"] [data-testid="stTab"] > div:last-child {
        background-color: transparent !important;
    }

    /* Progress bars — capacity meters */
    [data-testid="stProgress"] > div > div {
        background-color: #2D5DA8 !important;
        border-radius: 6px !important;
    }
    [data-testid="stProgress"] {
        background-color: #262B34 !important;
        border: 1px solid #55606F;
        border-radius: 6px !important;
    }

    /* Metric-style numbers, dataframes, tables — monospace like the JS version */
    [data-testid="stDataFrame"], [data-testid="stTable"] {
        font-family: 'IBM Plex Mono', monospace;
    }

    /* Captions and help text */
    [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p {
        color: #9BA5B2 !important;
    }

    /* Widget labels — "Power", "In-game name", "Highest troop tier", etc. */
    [data-testid="stWidgetLabel"] p,
    [data-testid="stWidgetLabel"] label,
    [data-testid="stWidgetLabel"] div {
        color: #C3CAD2 !important;
    }

    /* Radio button option text — "Single entry" / "Bulk entry" and similar */
    [data-testid="stRadio"] label p,
    [data-testid="stRadio"] div[role="radiogroup"] p,
    [data-testid="stCheckbox"] p {
        color: #EDEEF2 !important;
    }

    /* Plain markdown text (headings inside st.markdown, "Late joiners" labels,
       structure names, etc.) — deliberately targets only the <p> wrapper, not
       every descendant, so inline-colored spans like :orange[...]/:green[...]
       used for status text keep their own color instead of being overwritten. */
    [data-testid="stMarkdownContainer"] p {
        color: #EDEEF2 !important;
    }

    /* Selectbox / multiselect current-value text */
    [data-baseweb="select"] * {
        color: #EDEEF2 !important;
    }

    /* Tooltip popovers (the "?" help icons) and radio/checkbox accent dots use
       Streamlit's theme.toml directly rather than anything in this stylesheet —
       if that file isn't being picked up on someone's deployment for any reason,
       these fall back to Streamlit's stock light-mode look (white tooltip,
       barely-visible text; red radio dot) even though the rest of the app still
       looks right, since everything else here is explicit CSS, not theme-driven.
       Hardcoding these explicitly means the app looks correct even if
       config.toml never loads at all. */
    [data-testid="stTooltipContent"] {
        background-color: #3E4654 !important;
        color: #EDEEF2 !important;
        border: 1px solid #55606F !important;
    }
    [data-testid="stRadio"] input[type="radio"],
    [data-testid="stCheckbox"] input[type="checkbox"] {
        accent-color: #F0B02E !important;
    }
    /* The above targets the real (visually hidden) input for accessibility
       tools, but the dot everyone actually sees is a separately-styled div a
       few levels down — Streamlit hides the native control and draws its own,
       so accent-color alone has no visible effect without this too. */
    [data-testid="stRadioOption"][data-selected="true"] > div > div:first-child > div {
        background-color: #F0B02E !important;
    }

    /* Battle Plan cards — Castle's roster is always longer than the smaller
       turrets', which used to leave the Image button at a different height
       on every card. The column itself is already equal-height (Streamlit's
       own flex row does that by default); this makes the card fill that
       height too, then pushes its last child (the download button) to the
       bottom. Scoped to just these cards via their key prefix, not every
       nested card elsewhere, since only this row needs equalizing. */
    [data-testid="stLayoutWrapper"]:has([class*="st-key-bp_card_"]) {
        height: 100%;
    }
    [class*="st-key-bp_card_"] {
        height: 100%;
        display: flex;
        flex-direction: column;
    }
    [class*="st-key-bp_card_"] > [data-testid="stElementContainer"]:last-child {
        margin-top: auto;
        padding-top: 10px;
    }

    /* Sidebar-less layout: hide the empty sidebar toggle clutter if present */
    [data-testid="collapsedControl"] { display: none; }

    /* Mobile — narrow screens can't fit 5 equal-width structure tabs (or even
       the 3 top-level ones) without every label wrapping or truncating badly.
       Let the tab strip scroll horizontally instead of forcing a squeeze. */
    @media (max-width: 640px) {
        [data-testid="stTabs"] [role="tablist"] {
            overflow-x: auto;
            flex-wrap: nowrap;
            -webkit-overflow-scrolling: touch;
        }
        [data-testid="stTabs"] [data-testid="stTab"] {
            flex: 0 0 auto !important;
            padding-left: 14px;
            padding-right: 14px;
            white-space: nowrap;
        }
        h1 { font-size: 1.5rem !important; }
        [data-testid="stLayoutWrapper"] { padding: 8px 10px !important; }
        .kvk-fixed-header {
            position: static !important;
            padding: 10px 1rem 8px 1rem !important;
            border-bottom: none !important;
        }
        .kvk-header-spacer { height: 0 !important; }
        .kvk-header-title { font-size: 1.3rem !important; }
        .kvk-header-logo { height: 28px !important; }
    }

    /* Roster: the 21-column data table on wider screens, tap-friendly
       accordion cards below 768px — a table that wide is unusable on a
       phone no matter how it's styled, so this swaps the whole component
       rather than trying to squeeze it. */
    .st-key-mobile_roster { display: none; }
    @media (max-width: 768px) {
        .st-key-desktop_roster { display: none; }
        .st-key-mobile_roster { display: block; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

state = load_state()


def section_banner(label, color="#9BA5B2"):
    """A bannered section header — LEADER / BACKUP LEADER / JOINERS style, matching the
    look of a clearly-separated roster card instead of a wall of run-together text."""
    st.markdown(
        f'<div style="background:{color};color:#0F1115;padding:6px 10px;'
        f'font-family:\'Oswald\',sans-serif;font-size:13px;font-weight:700;'
        f'letter-spacing:0.8px;margin:16px 0 10px 0;border-radius:6px;'
        f'text-align:center;">{label.upper()}</div>',
        unsafe_allow_html=True,
    )


def _centered_line(text, bold=False, muted=False):
    color = "color:#9BA5B2;" if muted else ""
    tag = "b" if bold else "span"
    return f'<div style="text-align:center;padding:2px 0;{color}"><{tag}>{text}</{tag}></div>'


def render_role_sections(leader, backup, joiners_only, late_players=None):
    """Leader / Backup Leader / Joiners (/ Late joiners), each in its own bannered
    section with one name per line — used identically in the officer view and the
    player-facing Battle plan view so they always match."""
    section_banner("Leader", "#7B5FAE")
    if leader:
        name = _esc(leader.get("name") or "Unnamed")
        st.markdown(_centered_line(f"{name} ({_esc(leader['tier'])})", bold=True), unsafe_allow_html=True)
    else:
        st.markdown(_centered_line("Not yet assigned", muted=True), unsafe_allow_html=True)

    section_banner("Backup Leader", "#6B7684")
    if backup:
        name = _esc(backup.get("name") or "Unnamed")
        st.markdown(_centered_line(f"{name} ({_esc(backup['tier'])})", bold=True), unsafe_allow_html=True)
    else:
        st.markdown(_centered_line("Not yet assigned", muted=True), unsafe_allow_html=True)

    section_banner("Joiners", "#4E7A93")
    if joiners_only:
        for p in joiners_only:
            name = _esc(p.get("name") or "Unnamed")
            st.markdown(_centered_line(f"{name} ({_esc(p['tier'])})"), unsafe_allow_html=True)
    else:
        st.markdown(_centered_line("Empty — no one assigned yet.", muted=True), unsafe_allow_html=True)

    if late_players is not None:
        section_banner("Late Joiners", "#4CAF6B")
        if late_players:
            for p in late_players:
                name = _esc(p.get("name") or "Unnamed")
                st.markdown(_centered_line(f"{name} ({_esc(p.get('tier', ''))})", muted=True), unsafe_allow_html=True)
        else:
            st.markdown(_centered_line("None added.", muted=True), unsafe_allow_html=True)

# Whole-app gate: nobody sees any content until this passes. Keeps the app
# safe on a public URL — a search crawler can't get past a login screen either.
if not st.session_state.get("kingdom_authed"):
    render_header(state['kingdomName'])
    st.subheader("🔒 Kingdom access")
    with st.form("kingdom_gate_form"):
        pw = st.text_input("Passcode", type="password", key="kingdom_pw")
        submitted = st.form_submit_button("Enter", type="primary")
    if submitted:
        if pw == state["kingdomPasscode"]:
            st.session_state["kingdom_authed"] = True
            st.rerun()
        else:
            st.error("Wrong passcode.")
    st.stop()

render_header(state['kingdomName'])

with st.expander("ℹ️ How to use this board"):
    st.markdown(
        "**Player check-in:** enter your name, power, march size, troop tier, and Castle level. Once your "
        "power crosses the stat gate, rally size and troop stats also appear. Typing your name and clicking "
        "**Load previous entry** pulls up your last submission so you only need to update what's changed. "
        "Use **Bulk entry** if you're entering several people at once — pick "
        "\"Joiners (basic info)\" for people who'll just be joining a tower, or \"Rally leader candidates "
        "(with stats)\" for anyone who might end up leading one, since that needs their troop stats too.\n\n"
        "**Battle plan:** shows each tower's leader, joiners, late joiners, and target troop mix — once "
        "officers have published it. It's a frozen snapshot, not live — officers can keep adjusting things "
        "without it changing here until they publish again."
    )

query_params = st.query_params
officer_revealed = ("officer" in query_params) or st.session_state.get("officer_authed", False)

tab_labels = ["Player check-in", "Battle plan"]
if officer_revealed:
    tab_labels.append("Officer board")
tabs = st.tabs(tab_labels)
tab_checkin = tabs[0]
tab_battleplan = tabs[1]
tab_officer = tabs[2] if officer_revealed else None

# ---------- Player check-in ----------
with tab_checkin:
    submode = st.segmented_control(
        "Entry mode", ["Single entry", "Bulk entry"], default="Single entry",
        required=True, label_visibility="collapsed",
    )
    castle_opts = castle_level_options(state["maxCastleTG"])

    if submode == "Single entry":
        _, narrow_col, _ = st.columns([3, 2, 3])
        with narrow_col:
            if st.session_state.get("_clear_name_flag"):
                st.session_state["ci_name"] = ""
                st.session_state["_clear_name_flag"] = False

            if st.session_state.get("ci_last_saved"):
                st.success(f"Saved {st.session_state['ci_last_saved']}. Form's cleared — ready for the next person.")
                st.session_state["ci_last_saved"] = None

            st.caption("Enter your current stats so officers can plan garrison placement.")
            name = st.text_input("In-game name", key="ci_name")

            if st.button("Load previous entry"):
                if name.strip():
                    conn = get_conn()
                    row = conn.execute("SELECT value FROM players WHERE id = ?", (slugify(name),)).fetchone()
                    if row:
                        prev = json.loads(row[0])
                        st.session_state["ci_alliance"] = prev.get("alliance", "")
                        st.session_state["ci_power"] = float(prev.get("power", 0))
                        st.session_state["ci_march"] = float(prev.get("march", 0))
                        st.session_state["ci_tier"] = prev.get("tier", "T1")
                        st.session_state["ci_castle"] = prev.get("castleLevel", "1")
                        st.session_state["ci_rally"] = float(prev.get("rally", 0))
                        if prev.get("stats"):
                            for t in STAT_TYPES:
                                for f in STAT_FIELDS:
                                    st.session_state[f"ci_stat_{t}_{f}"] = float(prev["stats"].get(t, {}).get(f, 0))
                        st.success(f"Loaded previous entry for {prev['name']}.")
                    else:
                        st.info("No previous entry found for that name — this looks new.")
                st.rerun()

            with st.form("checkin_form", clear_on_submit=True):
                alliance = st.text_input("Alliance", key="ci_alliance", help="Which alliance you're currently in — helps officers plan across alliances if needed.")
                power = st.number_input("Power", min_value=0, step=1_000_000, key="ci_power")
                march = st.number_input("March size (max troops you can send)", min_value=0, step=10_000, key="ci_march")
                tier = st.selectbox("Highest troop tier", TIER_OPTIONS, key="ci_tier")
                castle_level = st.selectbox("Castle level", castle_opts, key="ci_castle")

                meets_gate = power >= state["statGateThreshold"]
                rally, stats = 0, None
                if meets_gate:
                    rally = st.number_input("Rally size (max troops you can lead)", min_value=0, step=10_000, key="ci_rally")
                    st.caption("Troop stats (%)")
                    stats = {}
                    for t in STAT_TYPES:
                        st.markdown(f"**{TYPE_MARK[t]} {t}**")
                        cols = st.columns(4)
                        stats[t] = {}
                        for i, f in enumerate(STAT_FIELDS):
                            stats[t][f] = cols[i].number_input(f, min_value=0.0, step=0.1, key=f"ci_stat_{t}_{f}")
                else:
                    st.caption(f"Rally size and troop stats unlock once your power reaches {fmt(state['statGateThreshold'])}.")

                submitted = st.form_submit_button("Submit stats", type="primary", width="stretch")

            if submitted:
                if not name.strip():
                    st.error("Enter your in-game name.")
                else:
                    entry = {
                        "id": slugify(name),
                        "name": name.strip(),
                        "alliance": alliance.strip(),
                        "power": int(power),
                        "march": int(march),
                        "tier": tier,
                        "castleLevel": castle_level,
                        "rally": int(rally) if meets_gate else 0,
                        "stats": stats,
                        "submittedAt": time.time(),
                    }
                    upsert_player(entry)
                    st.session_state["ci_last_saved"] = entry["name"]
                    st.session_state["_clear_name_flag"] = True
                    st.rerun()

    else:  # Bulk entry
        st.caption(
            "Pick whichever fits who you're entering. Joiners just need the basics — rally leader candidates "
            "need stats too, since that's what decides who actually leads a tower."
        )
        bulk_type = st.segmented_control(
            "Bulk entry type",
            ["Joiners (basic info)", "Rally leader candidates (with stats)"],
            default="Joiners (basic info)", required=True, label_visibility="collapsed",
        )

        stat_cols_ordered = [f"{TYPE_ABBR[t]} {FIELD_ABBR[f]}" for t in STAT_TYPES for f in STAT_FIELDS]
        base_cols = {"Name": "", "Alliance": "", "Power": 0, "March": 0, "Tier": "T1", "Castle": "1", "Rally": 0}
        base_column_config = {
            "Tier": st.column_config.SelectboxColumn(options=TIER_OPTIONS),
            "Castle": st.column_config.SelectboxColumn(options=castle_opts),
            "Power": st.column_config.NumberColumn(min_value=0),
            "March": st.column_config.NumberColumn(min_value=0),
            "Rally": st.column_config.NumberColumn(min_value=0),
        }

        if bulk_type == "Joiners (basic info)":
            st.caption(
                "No troop stats here — that's fine for people who'll just be joining a tower, not leading it. "
                "If any of these turn out to have rally-leader-level power, re-enter them with the other option."
            )
            editor_key_prefix = "bulk_joiners"
            columns_this_mode = base_cols
            column_config_this_mode = base_column_config
        else:
            st.caption(
                "Same basics, plus the 12 troop stat fields — needed because leader ranking is based on stats "
                "first. Leave a stat at 0 if you don't have it; it just won't count toward that person's ranking."
            )
            editor_key_prefix = "bulk_leaders"
            columns_this_mode = dict(base_cols)
            for col_name in stat_cols_ordered:
                columns_this_mode[col_name] = 0.0
            column_config_this_mode = dict(base_column_config)
            for col_name in stat_cols_ordered:
                column_config_this_mode[col_name] = st.column_config.NumberColumn(min_value=0.0, step=0.1, width="small")

        reset_key = f"{editor_key_prefix}_reset_counter"
        status_key = f"{editor_key_prefix}_last_status"
        loaded_key = f"{editor_key_prefix}_loaded_df"
        if reset_key not in st.session_state:
            st.session_state[reset_key] = 0
        if st.session_state.get(status_key):
            st.success(st.session_state[status_key])
            st.session_state[status_key] = None

        upload_col, template_col = st.columns([3, 1])
        with upload_col:
            uploaded = st.file_uploader(
                "Or upload a CSV/Excel file instead of typing",
                type=["csv", "xlsx", "xls"],
                key=f"{editor_key_prefix}_uploader_{st.session_state[reset_key]}",
            )
        with template_col:
            st.write("")
            template_df = pd.DataFrame([columns_this_mode])
            st.download_button(
                "⬇ CSV template",
                data=template_df.to_csv(index=False).encode("utf-8"),
                file_name=f"{editor_key_prefix}_template.csv",
                mime="text/csv",
                key=f"{editor_key_prefix}_template_dl",
                width="stretch",
            )

        if uploaded is not None:
            numeric_cols = ["Power", "March", "Rally"] + (
                stat_cols_ordered if bulk_type != "Joiners (basic info)" else []
            )
            parsed_df, msgs = parse_uploaded_bulk_file(
                uploaded, list(columns_this_mode.keys()), numeric_cols, TIER_OPTIONS, castle_opts,
            )
            if parsed_df is None:
                for m in msgs:
                    st.error(m)
            else:
                for m in msgs:
                    st.warning(m)
                st.session_state[loaded_key] = parsed_df
                st.session_state[status_key] = (
                    f"Loaded {len(parsed_df)} row(s) from {uploaded.name} — review below, then Submit all rows."
                )
                st.session_state[reset_key] += 1
                st.rerun()

        default_df = st.session_state.get(loaded_key)
        if default_df is None:
            default_df = pd.DataFrame([columns_this_mode])
        edited_df = st.data_editor(
            default_df,
            num_rows="dynamic",
            width="stretch",
            key=f"{editor_key_prefix}_editor_{st.session_state[reset_key]}",
            column_config=column_config_this_mode,
        )

        if st.button("Submit all rows", type="primary", key=f"{editor_key_prefix}_submit"):
            rows = edited_df[edited_df["Name"].astype(str).str.strip() != ""]
            saved = 0
            for _, row in rows.iterrows():
                if bulk_type == "Joiners (basic info)":
                    stats = None
                else:
                    stats = {}
                    for t in STAT_TYPES:
                        stats[t] = {}
                        for f in STAT_FIELDS:
                            col_name = f"{TYPE_ABBR[t]} {FIELD_ABBR[f]}"
                            stats[t][f] = float(row.get(col_name, 0) or 0)
                entry = {
                    "id": slugify(str(row["Name"])),
                    "name": str(row["Name"]).strip(),
                    "alliance": str(row.get("Alliance", "") or "").strip(),
                    "power": int(row["Power"] or 0),
                    "march": int(row["March"] or 0),
                    "tier": row["Tier"] or "T1",
                    "castleLevel": row["Castle"] or "1",
                    "rally": int(row["Rally"] or 0),
                    "stats": stats,
                    "submittedAt": time.time(),
                }
                upsert_player(entry)
                saved += 1
            st.session_state.pop(loaded_key, None)
            st.session_state[reset_key] += 1
            st.session_state[status_key] = f"Saved {saved} entries."
            st.rerun()

# ---------- Battle plan ----------
with tab_battleplan:
    plan = load_published_plan()
    if not plan:
        st.info("Officers haven't published a plan yet. Check back closer to KvK.")
    else:
        top_row = st.columns([3, 1])
        with top_row[0]:
            st.caption(f"Published {time.strftime('%Y-%m-%d %H:%M', time.localtime(plan['publishedAt']))}")
        with top_row[1]:
            st.download_button(
                "⬇ Download full plan",
                data=render_full_plan(plan),
                file_name=f"{slugify(plan.get('kingdomName', 'battle-plan'))}-battle-plan.png",
                mime="image/png",
                width="stretch",
            )

        plan_cols = st.columns(len(plan["structures"]))
        for col, s in zip(plan_cols, plan["structures"]):
            with col:
                with st.container(border=True, key=f"bp_card_{s['id']}"):
                    icon = structure_icon_html(s["kind"] == "castle", size=24)
                    st.markdown(
                        f'<div style="text-align:center;font-weight:700;font-size:1.05em;margin-bottom:4px;">{icon} {_esc(s["name"])}</div>',
                        unsafe_allow_html=True,
                    )
                    ratio_line = " / ".join(f"{s['ratio'].get(t, 0)}% {t}" for t in STAT_TYPES)
                    cap_note = " (leader's rally)" if s.get("leader") else ""
                    st.markdown(_centered_line(ratio_line, muted=True), unsafe_allow_html=True)
                    st.markdown(_centered_line(f"Capacity {fmt(s['capacity'])}{cap_note}", muted=True), unsafe_allow_html=True)
                    render_role_sections(
                        s.get("leader"), s.get("backupLeader"), s.get("joiners") or [],
                        late_players=s.get("lateJoiners") or [],
                    )
                    st.markdown('<div style="margin-top:14px;"></div>', unsafe_allow_html=True)
                    st.download_button(
                        "⬇ Image",
                        data=render_structure_card(s),
                        file_name=f"{slugify(s['name'])}.png",
                        mime="image/png",
                        key=f"dl_{s['id']}",
                        width="stretch",
                    )

# ---------- Officer board ----------
if tab_officer:
    with tab_officer:
        if not st.session_state.get("officer_authed"):
            st.subheader("🔒 Officer access")
            with st.form("officer_gate_form"):
                pw = st.text_input("Passcode", type="password", key="officer_pw")
                submitted = st.form_submit_button("Enter", type="primary")
            if submitted:
                if pw == state["officerPasscode"]:
                    st.session_state["officer_authed"] = True
                    st.rerun()
                else:
                    st.error("Wrong passcode.")
        else:
            with st.expander("📋 Officer quick guide", expanded=True):
                st.markdown(
                    "- **Leader & capacity:** each tower's leader is picked automatically — ranked by troop "
                    "stats first (weighted per role: Infantry leans on Health then Lethality; Archer and "
                    "Cavalry lean on Lethality), then rally size, then troop tier + Castle level combined, "
                    "then power. Once a tower has a leader, its real capacity becomes their rally size "
                    "automatically — the Starting capacity field below locks at that point, since it stops mattering.\n"
                    "- **Joiners** fill in by troop tier + Castle level first, then march size — not power. "
                    "A higher Castle level outranks the same troop tier, but a higher troop tier always beats "
                    "any Castle level below it.\n"
                    "- **Late joiners** is a manual backup list per tower — doesn't count against capacity.\n"
                    "- **Publish plan** freezes a snapshot for the Battle plan tab. Keep editing freely — "
                    "nothing reaches players until you publish again.\n"
                    "- **Kingdom passcode** (below) gates the whole app for everyone, including players. "
                    "**Officer passcode** is this tab specifically. This tab itself is hidden from the tab "
                    "bar unless the URL ends in `?officer=1` — bookmark that link and only share it with "
                    "fellow officers."
                )

            players = load_players()
            assignments, reserve, remaining, leaders, capacities, backup_leaders = assign(players, state["structures"], state["overrides"])

            plan = load_published_plan()
            pub_col1, pub_col2 = st.columns([3, 1])
            with pub_col1:
                if plan:
                    st.caption(f"Players are seeing the plan published {time.strftime('%Y-%m-%d %H:%M', time.localtime(plan['publishedAt']))}. Draft changes since then aren't visible to them yet.")
                else:
                    st.caption('Nothing published yet — players see "no plan yet" until you publish.')
            with pub_col2:
                if st.button("📢 Publish plan", type="primary", width="stretch"):
                    snapshot_structures = []
                    for s in state["structures"]:
                        leader = leaders[s["id"]]
                        backup = backup_leaders[s["id"]]
                        assigned = assignments[s["id"]]
                        exclude_ids = {p["id"] for p in [leader, backup] if p}
                        joiners = [p for p in assigned if p["id"] not in exclude_ids]
                        late_ids = s.get("lateJoiners", [])
                        late_players = [p for p in players if p["id"] in late_ids]
                        snapshot_structures.append({
                            "id": s["id"], "name": s["name"], "kind": s["kind"], "ratio": s["ratio"],
                            "capacity": capacities[s["id"]],
                            "leader": {"name": leader.get("name") or "Unnamed", "tier": leader["tier"], "rally": leader.get("rally", 0)} if leader else None,
                            "backupLeader": {"name": backup.get("name") or "Unnamed", "tier": backup["tier"]} if backup else None,
                            "joiners": [{"name": p.get("name") or "Unnamed", "tier": p["tier"]} for p in joiners],
                            "lateJoiners": [{"name": p.get("name") or "Unnamed", "tier": p["tier"]} for p in late_players],
                        })
                    save_published_plan({
                        "publishedAt": time.time(),
                        "kingdomName": state["kingdomName"],
                        "structures": snapshot_structures,
                    })
                    st.rerun()

            col1, col2 = st.columns(2)
            with col1:
                new_tg = st.number_input(
                    "Highest Castle Grade", min_value=1, value=state["maxCastleTG"],
                    help="How many Castle Grade (TG) tiers show up in the Castle level dropdown, past level 30. Raise it when the game adds a new grade.",
                )
                if new_tg != state["maxCastleTG"]:
                    state["maxCastleTG"] = new_tg
                    save_state(state)
            with col2:
                gate = st.number_input(
                    "Stat gate (power)", min_value=0, step=1_000_000, value=state["statGateThreshold"],
                    help="The power a player needs before rally size and troop stats appear on their check-in form.",
                )
                if gate != state["statGateThreshold"]:
                    state["statGateThreshold"] = gate
                    save_state(state)

            with st.expander("🔒 Security settings — officer and kingdom passcodes"):
                pcol1, pcol2 = st.columns(2)
                with pcol1:
                    new_pass = st.text_input(
                        "Officer passcode", value=state["officerPasscode"],
                        help="Required to open this tab. A shared code, not per-person login — anyone who has it gets full access.",
                    )
                    if new_pass != state["officerPasscode"]:
                        state["officerPasscode"] = new_pass
                        save_state(state)
                with pcol2:
                    new_kpass = st.text_input(
                        "Kingdom passcode", value=state["kingdomPasscode"],
                        help="Required for anyone, players included, to open this app at all. Separate from the officer passcode.",
                    )
                    if new_kpass != state["kingdomPasscode"]:
                        state["kingdomPasscode"] = new_kpass
                        save_state(state)

            if st.button("🔄 Refresh roster"):
                st.rerun()

            roster_col, structure_col = st.columns([1.2, 1])
            castle_opts_officer = castle_level_options(state["maxCastleTG"])

            with roster_col:
                st.subheader(f"Roster ({len(players)})")
                if "roster_reset_counter" not in st.session_state:
                    st.session_state["roster_reset_counter"] = 0
                if "roster_all_selected" not in st.session_state:
                    st.session_state["roster_all_selected"] = False

                toolbar = st.columns([1, 1, 2]) if players else st.columns([1, 3])
                if toolbar[0].button("+ Add player"):
                    pid = f"manual-{int(time.time() * 1000)}"
                    upsert_player({"id": pid, "name": "", "alliance": "", "power": 0, "rally": 0, "march": 0, "tier": "T1",
                                    "castleLevel": "1", "stats": None, "submittedAt": time.time()})
                    st.rerun()
                if players:
                    toggle_label = "Deselect all" if st.session_state["roster_all_selected"] else "Select all"
                    if toolbar[1].button(toggle_label):
                        st.session_state["roster_all_selected"] = not st.session_state["roster_all_selected"]
                        st.session_state["roster_reset_counter"] += 1
                        st.rerun()

                if players:
                    assign_options = ["Auto"] + [s["name"] for s in state["structures"]] + ["Reserve"]
                    name_to_id = {s["name"]: s["id"] for s in state["structures"]}
                    stat_cols_ordered = [f"{TYPE_ABBR[t]} {FIELD_ABBR[f]}" for t in STAT_TYPES for f in STAT_FIELDS]

                    rows = []
                    for p in players:
                        assign_label = compute_assign_label(state, p["id"])
                        row = {
                            "id": p["id"],
                            "Delete": st.session_state["roster_all_selected"],
                            "Name": p.get("name", ""), "Alliance": p.get("alliance", ""),
                            "Power": p.get("power", 0),
                            "Rally": p.get("rally", 0), "March": p.get("march", 0), "Tier": p.get("tier", "T1"),
                            "Castle": p.get("castleLevel", "1"),
                        }
                        stats = p.get("stats") or {}
                        for t in STAT_TYPES:
                            for f in STAT_FIELDS:
                                col_name = f"{TYPE_ABBR[t]} {FIELD_ABBR[f]}"
                                row[col_name] = float(stats.get(t, {}).get(f, 0))
                        row["Assign"] = assign_label
                        rows.append(row)
                    df = pd.DataFrame(rows)

                    column_config_roster = {
                        "id": None,
                        "Name": st.column_config.TextColumn(disabled=True),
                        "Power": st.column_config.NumberColumn(format="compact"),
                        "Rally": st.column_config.NumberColumn(format="compact"),
                        "March": st.column_config.NumberColumn(format="compact"),
                        "Tier": st.column_config.SelectboxColumn(options=TIER_OPTIONS),
                        "Castle": st.column_config.SelectboxColumn(options=castle_opts_officer),
                        "Assign": st.column_config.SelectboxColumn(options=assign_options),
                    }
                    for col_name in stat_cols_ordered:
                        column_config_roster[col_name] = st.column_config.NumberColumn(min_value=0.0, step=0.1, width="small")

                    with st.container(key="desktop_roster"):
                        edited = st.data_editor(
                            df, num_rows="fixed", width="stretch",
                            key=f"roster_editor_{st.session_state['roster_reset_counter']}",
                            column_config=column_config_roster,
                        )
                        if st.button("Apply roster changes", type="primary"):
                            for _, row in edited.iterrows():
                                if row["Delete"]:
                                    delete_player(row["id"])
                                    state["overrides"].pop(row["id"], None)
                                    continue
                                original = next((p for p in players if p["id"] == row["id"]), {})
                                new_stats = {}
                                for t in STAT_TYPES:
                                    new_stats[t] = {}
                                    for f in STAT_FIELDS:
                                        col_name = f"{TYPE_ABBR[t]} {FIELD_ABBR[f]}"
                                        new_stats[t][f] = float(row.get(col_name, 0) or 0)
                                upsert_player({
                                    **original, "id": row["id"], "name": original.get("name", ""),
                                    "alliance": row.get("Alliance", ""),
                                    "power": int(row["Power"]), "rally": int(row["Rally"]),
                                    "march": int(row["March"]), "tier": row["Tier"], "castleLevel": row["Castle"],
                                    "stats": new_stats,
                                })
                                if row["Assign"] == "Auto":
                                    state["overrides"].pop(row["id"], None)
                                elif row["Assign"] == "Reserve":
                                    state["overrides"][row["id"]] = "reserve"
                                else:
                                    state["overrides"][row["id"]] = name_to_id.get(row["Assign"])
                            save_state(state)
                            st.session_state["roster_all_selected"] = False
                            st.session_state["roster_reset_counter"] += 1
                            st.rerun()

                    with st.container(key="mobile_roster"):
                        for p in players:
                            assign_label = compute_assign_label(state, p["id"])
                            name = p.get("name") or "Unnamed"
                            alliance = p.get("alliance") or "—"
                            label = f"{name} [{alliance}] — {p.get('tier', 'T1')} {p.get('castleLevel', '1')}"
                            with st.expander(label):
                                c1, c2 = st.columns(2)
                                c1.metric("Power", fmt(p.get("power", 0)))
                                c2.metric("March", fmt(p.get("march", 0)))
                                if p.get("rally"):
                                    st.caption(f"Rally: {fmt(p['rally'])}")
                                new_assign = st.selectbox(
                                    "Assign", assign_options,
                                    index=assign_options.index(assign_label) if assign_label in assign_options else 0,
                                    key=f"mobile_assign_{p['id']}",
                                )
                                if new_assign != assign_label:
                                    if new_assign == "Auto":
                                        state["overrides"].pop(p["id"], None)
                                    elif new_assign == "Reserve":
                                        state["overrides"][p["id"]] = "reserve"
                                    else:
                                        state["overrides"][p["id"]] = name_to_id.get(new_assign)
                                    save_state(state)
                                    st.rerun()
                                if st.button("🗑 Delete player", key=f"mobile_delete_{p['id']}"):
                                    delete_player(p["id"])
                                    state["overrides"].pop(p["id"], None)
                                    save_state(state)
                                    st.rerun()
                        st.caption(
                            "Troop stats aren't editable here — use Bulk entry or the table view on a "
                            "wider screen for that."
                        )
                else:
                    st.info('No check-ins yet. Share the "Player check-in" tab of this app with your alliance, or add players manually.')

                st.markdown(f"**Reserve / rally force ({len(reserve)})**")
                if reserve:
                    st.dataframe(
                        pd.DataFrame([{"Name": p.get("name") or "Unnamed", "Tier": p["tier"], "March": fmt(p["march"])} for p in reserve]),
                        width="stretch", hide_index=True,
                    )
                else:
                    st.caption("Everyone fits in a garrison at current capacity.")

            with structure_col:
                st.subheader("Structures")
                if st.button("+ Add turret"):
                    sid = f"turret-{int(time.time() * 1000)}"
                    state["structures"].append({
                        "id": sid, "name": "New Turret", "kind": "turret", "capacity": 500_000,
                        "ratio": {"Infantry": 60, "Cavalry": 20, "Archer": 20}, "lateJoiners": [],
                    })
                    save_state(state)
                    st.rerun()

                structure_tab_labels = [s["name"] for s in state["structures"]]
                structure_tabs = st.tabs(structure_tab_labels)
                for tab, s in zip(structure_tabs, state["structures"]):
                    with tab:
                        _, center_col, _ = st.columns([1, 2, 1])
                        with center_col:
                            leader = leaders[s["id"]]
                            eff_capacity = capacities[s["id"]]
                            assigned = assignments[s["id"]]

                            is_castle = s["kind"] == "castle"
                            accent = "#2D5DA8" if is_castle else "#4E7A93"
                            icon = structure_icon_html(is_castle, size=28)
                            kind_label = "CASTLE" if is_castle else "TURRET"
                            st.markdown(
                                f'<div style="display:flex;align-items:center;gap:10px;margin:4px 0 12px 0;'
                                f'border-left:4px solid {accent};padding:2px 0 2px 10px;">'
                                f'<span style="font-size:22px;line-height:1;">{icon}</span>'
                                f'<span style="font-family:\'Oswald\',sans-serif;font-size:19px;font-weight:600;'
                                f'color:#EDEEF2;">{s["name"]}</span>'
                                f'<span style="background:{accent};color:#0F1115;padding:2px 8px;font-size:10px;'
                                f'font-weight:700;letter-spacing:0.5px;border-radius:4px;">{kind_label}</span>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )

                            new_name = st.text_input("Rename", value=s["name"], key=f"s_name_{s['id']}")
                            capacity_locked = leader is not None
                            new_capacity = st.number_input(
                                "Starting capacity", value=s["capacity"], key=f"s_cap_{s['id']}", step=50_000,
                                disabled=capacity_locked,
                                help=(
                                    f"Locked — capacity now comes automatically from {leader.get('name') or 'Unnamed'}'s rally size, so this number no longer does anything."
                                    if capacity_locked else
                                    "A placeholder used only until a leader with a rally size is assigned to this tower. Once that happens, capacity switches over automatically and this field locks."
                                ),
                            )
                            if s["kind"] != "castle" and st.button("✕ Remove this turret", key=f"s_del_{s['id']}"):
                                state["structures"] = [x for x in state["structures"] if x["id"] != s["id"]]
                                save_state(state)
                                st.rerun()
                            if new_name != s["name"] or (not capacity_locked and new_capacity != s["capacity"]):
                                s["name"] = new_name
                                if not capacity_locked:
                                    s["capacity"] = new_capacity
                                save_state(state)

                            if leader:
                                st.caption(f"Capacity **{fmt(eff_capacity)}** — from {leader.get('name') or 'Unnamed'}'s rally size")
                            else:
                                st.caption(f"Capacity **{fmt(eff_capacity)}** (starting capacity — no eligible leader on file yet)")

                            used = eff_capacity - remaining.get(s["id"], eff_capacity)
                            pct = min(1.0, used / eff_capacity) if eff_capacity > 0 else 0
                            st.progress(pct, text=f"{fmt(used)} / {fmt(eff_capacity)} ({pct*100:.0f}%)")
                            if used > eff_capacity:
                                st.markdown(":red[⚠ overloaded]")
                            elif pct < 0.7:
                                st.markdown(":orange[⚠ understaffed]")
                            else:
                                st.markdown('<span style="color:#4CAF6B;font-weight:600;">optimal</span>', unsafe_allow_html=True)

                            rcols = st.columns(3)
                            changed = False
                            for i, t in enumerate(STAT_TYPES):
                                val = rcols[i].number_input(f"{t} %", value=s["ratio"][t], key=f"s_ratio_{s['id']}_{t}", step=5)
                                if val != s["ratio"][t]:
                                    s["ratio"][t] = val
                                    changed = True
                            if changed:
                                save_state(state)

                            backup = backup_leaders[s["id"]]
                            exclude_ids = {p["id"] for p in [leader, backup] if p}
                            joiners_only = [p for p in assigned if p["id"] not in exclude_ids]
                            render_role_sections(leader, backup, joiners_only)

                            section_banner("Late Joiners", "#4CAF6B")
                            late_ids = s.get("lateJoiners", [])
                            late_players = [p for p in players if p["id"] in late_ids]
                            if late_players:
                                for p in late_players:
                                    st.markdown(_centered_line(_esc(p.get("name") or "Unnamed"), muted=True), unsafe_allow_html=True)
                            else:
                                st.markdown(_centered_line("None added.", muted=True), unsafe_allow_html=True)

                            # Exclude anyone already committed anywhere — assigned (leader,
                            # backup, or joiner) to any structure, or already a late joiner
                            # on any structure — so the same person can't be double-booked.
                            committed_ids = set()
                            for other_s in state["structures"]:
                                committed_ids.update(p["id"] for p in assignments.get(other_s["id"], []))
                                committed_ids.update(other_s.get("lateJoiners", []))
                            available = [p for p in players if p["id"] not in committed_ids]
                            if available:
                                st.markdown('<div style="margin-top:10px;"></div>', unsafe_allow_html=True)
                                add_pick = st.selectbox(
                                    "Add late joiner", ["—"] + [p.get("name") or p["id"] for p in available],
                                    key=f"late_add_{s['id']}", label_visibility="collapsed",
                                )
                                if add_pick != "—":
                                    add_col, remove_col = st.columns(2)
                                    if add_col.button("+ Add", key=f"late_add_btn_{s['id']}"):
                                        match = next((p for p in available if (p.get("name") or p["id"]) == add_pick), None)
                                        if match:
                                            s["lateJoiners"] = late_ids + [match["id"]]
                                            save_state(state)
                                            st.rerun()
                            if late_players:
                                st.markdown('<div style="margin-top:10px;"></div>', unsafe_allow_html=True)
                                remove_pick = st.selectbox(
                                    "Remove late joiner", ["—"] + [p.get("name") or p["id"] for p in late_players],
                                    key=f"late_remove_{s['id']}", label_visibility="collapsed",
                                )
                                if remove_pick != "—" and st.button("− Remove", key=f"late_remove_btn_{s['id']}"):
                                    match = next((p for p in late_players if (p.get("name") or p["id"]) == remove_pick), None)
                                    if match:
                                        s["lateJoiners"] = [pid for pid in late_ids if pid != match["id"]]
                                        save_state(state)
                                        st.rerun()
