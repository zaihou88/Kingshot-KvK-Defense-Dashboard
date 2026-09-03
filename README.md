# KvK Defense Board — Python version

A self-hosted alternative to the Claude-artifact version of the same tool,
now rebuilt to match it feature-for-feature: leader auto-selection with
capacity drawn from their rally size, Castle level + TG grading, per-troop-type
stat weighting, tier+Castle-level joiner ranking, late joiners, a published
Battle Plan tab, a kingdom-wide passcode gate, and a hidden officer tab.

## Run it locally

```bash
pip install -r requirements.txt
streamlit run kvk_defense_board.py
```

This opens the app in your browser at `http://localhost:8501`. Data is
stored in a local file, `kvk_board.db` (SQLite), created next to the script
the first time you run it.

You'll land on the Kingdom passcode screen first (default `kingdom2159`).
The Officer board tab is hidden until you open the app with `?officer=1` on
the end of the URL, e.g. `http://localhost:8501/?officer=1` — bookmark that
variant for yourself and change both passcodes immediately from the
defaults once you're in (Officer board's settings row).

## Files in this folder

- `kvk_defense_board.py` — the app. Shouldn't normally need editing.
- `USER_GUIDE.md` — a separate, non-technical guide for your alliance,
  written for anyone who ends up on this GitHub page looking for help
  instead of you. It deliberately says nothing about the officer side —
  same reasoning as the in-app help panel, no point advertising it exists.
  Doesn't need editing unless you want to add kingdom-specific notes.
- `config.py` — the one file meant for hand-editing: troop stat weights
  (`STAT_WEIGHTS`), default structures, default passcodes and stat gate.
  Change a value, save, commit, push — Streamlit Cloud redeploys
  automatically. Note: the defaults in here only seed a *brand-new* board;
  once the app has real data in `kvk_board.db`, passcodes and the stat
  gate are managed from the Officer board UI instead.
- `battle_plan_image.py` — generates the downloadable Battle Plan images
  (per-structure and full-plan). Shouldn't normally need editing.
- `fonts/` — the actual font files (Oswald, Barlow, IBM Plex Mono) used by
  both the app's styling and the generated images, bundled so they render
  correctly regardless of what's installed on the host. Upload this whole
  folder to GitHub too.
- `icons/` — Castle and Turret artwork plus the Kingshot logo, used the same
  bundled way as `fonts/` (base64-embedded so nothing depends on file paths
  at runtime). Also needs to be uploaded to GitHub as a whole folder. If it's
  ever missing, the app falls back to plain 🏰/🗼 emoji instead of breaking.
- `seed_test_data.py` — optional. Run `python3 seed_test_data.py` to drop
  ~11 fake players (alliances, stats, rally sizes) into `kvk_board.db` for
  testing. Their names are all prefixed `Test-` so they're easy to find and
  delete from the Officer board roster afterward.
- `requirements.txt` — tells Streamlit Cloud what Python packages to install.
- `.streamlit/config.toml` — base theme colors (a backup layer — see below).
- `README.md` — this file.

## If it looks plain / white instead of styled

The app now injects its own styling directly in `kvk_defense_board.py`
(fonts, colors, borders, buttons), so this shouldn't happen — but if it
does, it almost always means the `.streamlit` folder didn't come across
correctly, either when copying files locally or in the GitHub upload.
Folders starting with a dot are hidden by default in Finder/Explorer, so
it's easy to lose without noticing. Check that a `.streamlit` folder
containing `config.toml` genuinely exists next to `kvk_defense_board.py` —
if you're running locally, `ls -la` in that folder will show it if it's
there. This only affects a handful of base colors though; the real styling
comes from the CSS built into the app itself, so a missing `.streamlit`
folder shouldn't cause a fully white/unstyled app anymore.

## Sharing it with your kingdom

Running it locally only puts it on your own machine. To get it reachable from
the internet — without it being guessable or search-engine-indexable — deploy
it free on Streamlit Community Cloud, protected by the app's own Kingdom
passcode gate:

1. **Create a GitHub account** (free) if you don't have one for this — a
   dedicated one for the game is a reasonable idea if you'd rather keep it
   separate from anything personal.
2. **Create a new repository** on GitHub (public is fine — the passcode is
   stored in the app's data, not in the code, so a public repo doesn't leak
   it) and upload this folder's contents: `kvk_defense_board.py`,
   `config.py`, `requirements.txt`, and the `.streamlit/config.toml` file.
3. **Go to share.streamlit.io** and sign in — it uses GitHub to log in, so
   your new GitHub account covers this too, no separate signup.
4. Click **"New app"**, point it at your repository and
   `kvk_defense_board.py`, and deploy. Streamlit gives you a URL like
   `https://your-app-name.streamlit.app`.
5. **Open that URL and log in with the default Kingdom passcode**
   (`kingdom2159`) — then open `<your-url>/?officer=1`, log in with the
   default officer passcode (`2159`), and change both passcodes to
   something real in the settings row.
6. Send the plain app URL **and** the Kingdom passcode to your whole
   alliance. Send `<your-url>/?officer=1` **and** the officer passcode
   privately to your fellow officers only — that variant is what reveals
   the Officer board tab at all.

This is genuinely free — no credit card, no time limit on Streamlit
Community Cloud's free tier for an app this size.

A few practical notes:

- **The Kingdom passcode gates the entire app** — check-in, everything —
  before anyone even sees a tab. The Officer passcode is a second, separate
  gate just for the Officer board, same as before.
- Streamlit Community Cloud apps can sleep after a period of no visitors and
  take a few seconds to wake back up on the next visit — normal, not a bug.
- Back up `kvk_board.db` (download it directly from wherever it's hosted,
  or copy it locally) before any redeploy once real roster data is in
  there — Streamlit Cloud's disk isn't guaranteed to survive every
  redeploy.

## How this differs from the Claude-artifact version

- The artifact version needs no hosting — Anthropic serves the published
  link and its storage for you, but data lives inside that specific
  artifact and is deleted if it's ever unpublished.
- This version needs you to host it, but the data is a plain SQLite file
  you fully own and can back up, inspect, or migrate yourself.

## How to use it

**Players:** open the app, enter the Kingdom passcode, and stay on "Player
check-in." Enter your name, alliance, power, march size, troop tier, and
Castle level. Once your power crosses the stat gate, rally size and troop
stats also appear. Click "Load previous entry" after typing your name to
pull up your last submission and just update what changed. Use "Bulk
entry" and pick "Joiners" or "Rally leader candidates" depending on who
you're entering — only the latter needs troop stats. Either mode also
accepts a CSV or Excel upload instead of typing rows by hand — there's a
template download button next to the uploader with the exact columns
expected; an uploaded file gets loaded into the editable grid for review
before anything actually saves, and rows with an unrecognized Tier or
Castle level get reset to a safe default rather than rejected outright.
Check the "Battle
plan" tab to see each tower's leader, joiners, and target troop mix once
officers publish it — a "Download" button there saves it as an image,
either the whole plan or one structure at a time.

**Officers:** open `<your-url>/?officer=1` and enter the officer passcode.
From there you can edit anyone's numbers, add or remove structures (each
one gets its own tab so the list doesn't turn into an endless scroll as
your roster grows), set the stat gate and Highest Castle Grade, manage
each tower's late-joiners list, and override who defends where. Each
tower's leader and capacity are picked automatically — see the "Officer
quick guide" inside that tab for exactly how. Nothing reaches the Battle
plan tab until you click "Publish plan."
