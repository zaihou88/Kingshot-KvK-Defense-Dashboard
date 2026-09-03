"""
KvK Defense Board — tunable settings

This is the one file meant to be hand-edited when something about the game
changes. Everything else (kvk_defense_board.py) is app logic and shouldn't
normally need touching.

After changing anything here: save, commit, push to GitHub. Streamlit
Community Cloud redeploys automatically within a minute or two.
"""

from pathlib import Path

# Where the shared roster/settings database lives. Leave this alone unless
# you know you want to change it.
DB_PATH = Path(__file__).parent / "kvk_board.db"


# ---------- troop stats ----------

STAT_TYPES = ["Infantry", "Cavalry", "Archer"]
STAT_FIELDS = ["Attack", "Defense", "Lethality", "Health"]

# Fixed troop tier options. The in-game cap is currently T10 — raise the
# range here if the game ever adds a higher tier.
TIER_OPTIONS = [f"T{i}" for i in range(1, 11)]

# Small marker shown next to each troop type in the check-in form and
# officer board. Purely cosmetic — change or remove freely.
TYPE_MARK = {"Infantry": "🟩", "Cavalry": "🟧", "Archer": "🟦"}

# How much each stat counts toward a player's leader-ranking score.
# Higher number = more influence. These don't need to add up to anything
# in particular — only the ratios between them matter.
#
# Current reasoning: Infantry leans on Health first, then Lethality
# (frontline survivability matters most). Archer and Cavalry lean on
# Lethality (they're valued for the damage they land). Change this
# whenever the community's sense of what matters shifts — new heroes,
# new gear, a patch that reweights combat formulas, etc.
STAT_WEIGHTS = {
    "Infantry": {"Attack": 1, "Defense": 1, "Lethality": 2, "Health": 3},
    "Cavalry": {"Attack": 1, "Defense": 1, "Lethality": 3, "Health": 1},
    "Archer": {"Attack": 1, "Defense": 1, "Lethality": 3, "Health": 1},
}
# Derived automatically from the weights above — no need to touch this.
STAT_TOTAL_WEIGHT = sum(STAT_WEIGHTS[t][f] for t in STAT_TYPES for f in STAT_FIELDS)


# ---------- default structures ----------
# Only used the very first time the app runs (creates the initial board).
# Once real data exists in kvk_board.db, officers manage structures from
# the Officer board UI instead — editing this afterward won't change an
# already-running board.

DEFAULT_STRUCTURES = [
    {"id": "castle", "name": "Castle", "kind": "castle", "capacity": 3_000_000,
     "ratio": {"Infantry": 60, "Cavalry": 20, "Archer": 20}, "lateJoiners": []},
    {"id": "turret-n", "name": "Turret North", "kind": "turret", "capacity": 1_200_000,
     "ratio": {"Infantry": 60, "Cavalry": 20, "Archer": 20}, "lateJoiners": []},
    {"id": "turret-s", "name": "Turret South", "kind": "turret", "capacity": 1_200_000,
     "ratio": {"Infantry": 60, "Cavalry": 20, "Archer": 20}, "lateJoiners": []},
    {"id": "turret-e", "name": "Turret East", "kind": "turret", "capacity": 1_200_000,
     "ratio": {"Infantry": 60, "Cavalry": 20, "Archer": 20}, "lateJoiners": []},
    {"id": "turret-w", "name": "Turret West", "kind": "turret", "capacity": 1_200_000,
     "ratio": {"Infantry": 60, "Cavalry": 20, "Archer": 20}, "lateJoiners": []},
]

# ---------- default board settings ----------
# Same caveat as above: only seeds a brand-new board. Change passcodes and
# the stat gate from the Officer board UI once the app is actually running
# — editing them here afterward has no effect on existing data.

DEFAULT_STATE = {
    "kingdomName": "Kingdom 2159 KOR",
    "structures": DEFAULT_STRUCTURES,
    "overrides": {},
    "officerPasscode": "2159",
    "kingdomPasscode": "kingdom2159",
    "statGateThreshold": 100_000_000,
    "maxCastleTG": 8,
}
