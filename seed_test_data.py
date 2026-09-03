"""
Seed test players into kvk_board.db for trying out the board — the "full" version.

Run with:  python3 seed_test_data.py

This writes ~34 fake players directly into kvk_board.db (same folder), tuned
so that Castle and all four turrets each end up with a Leader, a Backup
Leader, several Joiners, and a couple of Late Joiners — plus a few players
who overflow into Reserve, so every part of the board has something to look
at. All names are prefixed "Test-" so they're easy to find and delete from
the Officer board roster afterward.

To remove them again: delete kvk_board.db and restart fresh, or delete each
one manually from the Officer board roster table.
"""

import json
import re
import sqlite3
import time

from config import DB_PATH, DEFAULT_STATE


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "player"


def stats(inf=None, cav=None, arc=None):
    zero = {"Attack": 0, "Defense": 0, "Lethality": 0, "Health": 0}
    return {
        "Infantry": {**zero, **(inf or {})},
        "Cavalry": {**zero, **(cav or {})},
        "Archer": {**zero, **(arc or {})},
    }


TEST_PLAYERS = []

# ---- 5 leader candidates — strictly decreasing stat strength, one per structure ----
LEADERS = [
    dict(name="Test-Boyoung", alliance="Alpha", power=180_000_000, march=350_000, tier="T10",
         castleLevel="TG3", rally=1_800_000,
         stats=stats(inf={"Attack": 60, "Defense": 60, "Lethality": 90, "Health": 100})),
    dict(name="Test-Raff", alliance="Alpha", power=165_000_000, march=300_000, tier="T10",
         castleLevel="TG2", rally=1_200_000,
         stats=stats(arc={"Attack": 55, "Defense": 45, "Lethality": 85, "Health": 60})),
    dict(name="Test-Officer3", alliance="Bravo", power=150_000_000, march=250_000, tier="T9",
         castleLevel="TG1", rally=900_000,
         stats=stats(cav={"Attack": 50, "Defense": 40, "Lethality": 80, "Health": 55})),
    dict(name="Test-SouthLead", alliance="Bravo", power=120_000_000, march=120_000, tier="T9",
         castleLevel="28", rally=500_000,
         stats=stats(inf={"Attack": 40, "Defense": 35, "Lethality": 65, "Health": 75})),
    dict(name="Test-WestLead", alliance="Charlie", power=110_000_000, march=70_000, tier="T9",
         castleLevel="26", rally=300_000,
         stats=stats(arc={"Attack": 35, "Defense": 30, "Lethality": 60, "Health": 40})),
]

# ---- 5 backup-leader candidates — deliberately below all 5 leaders, above all joiners.
#      All still above the stat gate (100M), same as the leaders — that's what makes
#      them eligible to have stats/rally on file in the first place. ----
BACKUPS = [
    dict(name="Test-BackupA", alliance="Alpha", power=104_000_000, march=180_000, tier="T9",
         castleLevel="TG1", rally=700_000,
         stats=stats(inf={"Attack": 25, "Defense": 25, "Lethality": 40, "Health": 50})),
    dict(name="Test-BackupB", alliance="Bravo", power=103_000_000, march=150_000, tier="T9",
         castleLevel="27", rally=400_000,
         stats=stats(arc={"Attack": 22, "Defense": 20, "Lethality": 38, "Health": 28})),
    dict(name="Test-BackupC", alliance="Charlie", power=102_000_000, march=140_000, tier="T8",
         castleLevel="24", rally=350_000,
         stats=stats(cav={"Attack": 20, "Defense": 18, "Lethality": 35, "Health": 25})),
    dict(name="Test-BackupD", alliance="Alpha", power=101_000_000, march=90_000, tier="T8",
         castleLevel="23", rally=250_000,
         stats=stats(inf={"Attack": 18, "Defense": 16, "Lethality": 28, "Health": 32})),
    dict(name="Test-BackupE", alliance="Bravo", power=100_000_000, march=50_000, tier="T8",
         castleLevel="20", rally=150_000,
         stats=stats(arc={"Attack": 15, "Defense": 14, "Lethality": 25, "Health": 18})),
]
TEST_PLAYERS.extend(LEADERS)
TEST_PLAYERS.extend(BACKUPS)

# ---- ~24 regular joiners — no rally, spread of type/tier/alliance, enough march
#      tonnage to fill each structure's leftover capacity without every single one
#      fitting (a few overflow to Reserve, so that panel has something in it too) ----
JOINER_SPECS = [
    # (name, type_for_stats, tier, castle, power, march, alliance)
    # Typed joiners (have stats) are kept above the 100M gate, same reasoning as
    # the leaders/backups — that's the only way stats would exist on their check-in
    # in the first place. Power itself doesn't affect fill order (that's tier +
    # Castle level + march only), so bumping it here doesn't change who goes where.
    ("Test-Inf1", "inf", "T9", "25", 140_000_000, 220_000, "Alpha"),
    ("Test-Inf2", "inf", "T8", "22", 130_000_000, 200_000, "Bravo"),
    ("Test-Inf3", "inf", "T8", "20", 125_000_000, 180_000, "Charlie"),
    ("Test-Inf4", "inf", "T7", "18", 118_000_000, 150_000, "Alpha"),
    ("Test-Inf5", "inf", "T7", "16", 112_000_000, 130_000, "Bravo"),
    ("Test-Inf6", "inf", "T6", "14", 105_000_000, 100_000, "Charlie"),
    ("Test-Cav1", "cav", "T9", "24", 138_000_000, 210_000, "Bravo"),
    ("Test-Cav2", "cav", "T8", "21", 128_000_000, 190_000, "Charlie"),
    ("Test-Cav3", "cav", "T7", "17", 116_000_000, 140_000, "Alpha"),
    ("Test-Cav4", "cav", "T7", "15", 110_000_000, 120_000, "Bravo"),
    ("Test-Cav5", "cav", "T6", "13", 103_000_000, 90_000, "Charlie"),
    ("Test-Arc1", "arc", "T9", "23", 136_000_000, 200_000, "Alpha"),
    ("Test-Arc2", "arc", "T8", "20", 126_000_000, 175_000, "Bravo"),
    ("Test-Arc3", "arc", "T8", "19", 122_000_000, 165_000, "Charlie"),
    ("Test-Arc4", "arc", "T7", "16", 114_000_000, 125_000, "Alpha"),
    ("Test-Arc5", "arc", "T6", "14", 106_000_000, 105_000, "Bravo"),
    ("Test-Arc6", "arc", "T6", "12", 101_000_000, 95_000, "Charlie"),
    ("Test-Joiner1", "inf", "T9", "25", 110_000_000, 250_000, "Alpha"),  # above stat gate, no rally submitted
    # Below the stat gate — no stats on file, which is exactly what the real
    # check-in form would do for them too.
    ("Test-Joiner2", None, "T8", "22", 95_000_000, 200_000, "Charlie"),
    ("Test-Joiner3", None, "T7", "18", 60_000_000, 150_000, "Charlie"),
    ("Test-Joiner4", None, "T6", "15", 45_000_000, 100_000, "Alpha"),
    ("Test-Joiner5", None, "T5", "10", 30_000_000, 80_000, "Bravo"),
    ("Test-Newbie1", None, "T3", "6", 8_000_000, 20_000, "Charlie"),
    ("Test-Newbie2", None, "T2", "4", 5_000_000, 15_000, "Alpha"),
]

for name, tflag, tier, castle, power, march, alliance in JOINER_SPECS:
    if tflag == "inf":
        s = stats(inf={"Attack": 15, "Defense": 15, "Lethality": 25, "Health": 30})
    elif tflag == "cav":
        s = stats(cav={"Attack": 12, "Defense": 10, "Lethality": 22, "Health": 12})
    elif tflag == "arc":
        s = stats(arc={"Attack": 12, "Defense": 10, "Lethality": 22, "Health": 12})
    else:
        s = None
    TEST_PLAYERS.append(dict(
        name=name, alliance=alliance, power=power, march=march, tier=tier,
        castleLevel=castle, rally=0, stats=s,
    ))

# ---- Late joiners — 2 per structure, matched by structure name. If you've
#      renamed a structure, its late-joiners just won't get seeded; everything
#      else still works. ----
LATE_JOINERS_BY_STRUCTURE_NAME = {
    "Castle": ["Test-Newbie1", "Test-Joiner2"],
    "Turret North": ["Test-Newbie2", "Test-Joiner3"],
    "Turret South": ["Test-Cav5", "Test-Joiner5"],
    "Turret East": ["Test-Arc6", "Test-Inf6"],
    "Turret West": ["Test-Cav4", "Test-Inf5"],
}


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS players (id TEXT PRIMARY KEY, value TEXT)")

    for p in TEST_PLAYERS:
        entry = {
            "id": slugify(p["name"]),
            "name": p["name"],
            "alliance": p["alliance"],
            "power": p["power"],
            "march": p["march"],
            "tier": p["tier"],
            "castleLevel": p["castleLevel"],
            "rally": p["rally"],
            "stats": p["stats"],
            "submittedAt": time.time(),
        }
        conn.execute(
            "INSERT OR REPLACE INTO players (id, value) VALUES (?, ?)",
            (entry["id"], json.dumps(entry)),
        )

    # Add late joiners to whichever structures already exist under the board's
    # current state, without touching anything else an officer has configured.
    row = conn.execute("SELECT value FROM config WHERE key='board'").fetchone()
    state = dict(DEFAULT_STATE)
    if row:
        state.update(json.loads(row[0]))

    matched = 0
    for s in state["structures"]:
        names = LATE_JOINERS_BY_STRUCTURE_NAME.get(s["name"])
        if names:
            ids = [slugify(n) for n in names]
            existing = s.get("lateJoiners", [])
            s["lateJoiners"] = list(dict.fromkeys(existing + ids))  # de-duped, order preserved
            matched += 1
    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('board', ?)", (json.dumps(state),))

    conn.commit()
    conn.close()
    print(f"Seeded {len(TEST_PLAYERS)} test players into {DB_PATH}")
    print(f"Added late joiners to {matched} structure(s).")
    print("Names are all prefixed 'Test-' so they're easy to find and delete later.")


if __name__ == "__main__":
    main()
