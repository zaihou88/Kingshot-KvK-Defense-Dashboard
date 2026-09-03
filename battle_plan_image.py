"""
Battle Plan image export.

Renders published battle-plan data as PNG images directly with Pillow,
matching the app's dark ops-board look. Server-side and deterministic —
no browser screenshot tricks, no JS, works identically regardless of who's
viewing the page or which browser they're on.
"""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).parent / "fonts"
ICON_DIR = Path(__file__).parent / "icons"


def _load_icon(filename, size):
    """Loads a bundled icon at the given pixel size. Returns None if missing —
    callers fall back to text-only, same defensive pattern as font loading."""
    try:
        img = Image.open(ICON_DIR / filename).convert("RGBA")
        return img.resize((size, size), Image.LANCZOS)
    except OSError:
        return None

BG = (38, 43, 52)
PANEL = (62, 70, 84)
BORDER = (85, 96, 111)
TEXT = (237, 238, 242)
MUTED = (155, 165, 178)
BLUE = (45, 93, 168)
PURPLE = (123, 95, 174)
GREEN = (76, 175, 107)
BACKUP_GRAY = (107, 118, 132)
STEEL = (78, 122, 147)
RED = (180, 72, 60)
TYPE_COLORS = {
    "Infantry": (107, 143, 113),
    "Cavalry": (160, 105, 63),
    "Archer": (78, 122, 147),
}

CARD_WIDTH = 480
PAD = 20
GAP = 16
RADIUS = 10
BANNER_RADIUS = 6


def _font(family, size, bold=False):
    """Loads the bundled font, falling back to Pillow's built-in font instead of
    crashing if the fonts/ folder is ever missing or misplaced next to this file."""
    try:
        if family == "oswald":
            f = ImageFont.truetype(str(FONT_DIR / "Oswald-Variable.ttf"), size)
            f.set_variation_by_name("Bold" if bold else "SemiBold")
            return f
        if family == "mono":
            path = FONT_DIR / ("IBMPlexMono-SemiBold.ttf" if bold else "IBMPlexMono-Regular.ttf")
            return ImageFont.truetype(str(path), size)
        path = FONT_DIR / ("Barlow-SemiBold.ttf" if bold else "Barlow-Regular.ttf")
        return ImageFont.truetype(str(path), size)
    except OSError:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()


def _truncate(draw, text, font, max_width):
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…"


def _fmt(n):
    n = n or 0
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def _banner_height():
    return 26


def _draw_banner(d, x, y, width, label, color):
    font = _font("oswald", 13, bold=True)
    d.rounded_rectangle([x, y, x + width, y + _banner_height() - 4], radius=BANNER_RADIUS, fill=color)
    d.text((x + 8, y + 4), label.upper(), font=font, fill=BG)


def _measure_card_height(s):
    """Precompute how tall a structure card needs to be for its content."""
    y = PAD
    y += 34  # header row (name + kind badge)
    y += 26  # ratio bar
    y += 22  # ratio text
    y += 22  # capacity text

    y += _banner_height() + 4 + 22  # LEADER banner + one line
    y += _banner_height() + 4 + 22  # BACKUP LEADER banner + one line

    y += _banner_height() + 4  # JOINERS banner
    joiners = s.get("joiners") or []
    if joiners:
        y += len(joiners) * 20
    else:
        y += 20

    late = s.get("lateJoiners") or []
    y += _banner_height() + 4  # LATE JOINERS banner
    if late:
        y += len(late) * 20
    else:
        y += 20

    y += PAD
    return y


def render_structure_card(s):
    """Render one structure (Castle or a turret) as a standalone PNG. Returns PNG bytes."""
    height = _measure_card_height(s)
    # Canvas is the app background; the card itself is a rounded, inset panel on
    # top of it — rounding only reads visually if something else shows through
    # the corners, which a flat same-color rectangle can't do.
    img = Image.new("RGB", (CARD_WIDTH, height), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, CARD_WIDTH - 2, height - 2], radius=RADIUS, fill=PANEL, outline=BORDER, width=1)

    is_castle = s.get("kind") == "castle"
    accent = BLUE if is_castle else STEEL
    kind_label = "CASTLE" if is_castle else "TURRET"

    x = PAD
    y = PAD
    d.rounded_rectangle([2, RADIUS, 7, height - RADIUS], radius=3, fill=accent)

    icon_size = 30
    icon_img = _load_icon("castle.png" if is_castle else "turret.png", icon_size)
    name_x = x + 6
    if icon_img:
        img.paste(icon_img, (x + 6, y - 2), icon_img)
        name_x = x + 6 + icon_size + 8

    header_font = _font("oswald", 22, bold=True)
    d.text((name_x, y + 3), s["name"], font=header_font, fill=TEXT)
    badge_font = _font("barlow", 12, bold=True)
    badge_w = d.textlength(kind_label, font=badge_font) + 16
    d.rounded_rectangle([CARD_WIDTH - PAD - badge_w, y + 4, CARD_WIDTH - PAD, y + 26], radius=4, fill=accent)
    d.text((CARD_WIDTH - PAD - badge_w + 8, y + 6), kind_label, font=badge_font, fill=BG)
    y += 34

    inner_w = CARD_WIDTH - 2 * PAD - 6
    ratio = s.get("ratio", {})
    bar_x = x + 6
    total_pct = sum(ratio.get(t, 0) for t in TYPE_COLORS) or 100
    cursor = bar_x
    bar_h = 10
    for t, color in TYPE_COLORS.items():
        seg = inner_w * (ratio.get(t, 0) / total_pct)
        d.rectangle([cursor, y, cursor + seg, y + bar_h], fill=color)
        cursor += seg
    d.rounded_rectangle([bar_x, y, bar_x + inner_w, y + bar_h], radius=4, outline=BORDER, width=1)
    y += bar_h + 6

    ratio_font = _font("barlow", 13)
    ratio_text = " / ".join(f"{ratio.get(t, 0)}% {t}" for t in TYPE_COLORS)
    d.text((x + 6, y), ratio_text, font=ratio_font, fill=MUTED)
    y += 22

    cap_note = " (leader's rally)" if s.get("leader") else " (fallback)"
    d.text((x + 6, y), f"Capacity {_fmt(s.get('capacity'))}{cap_note}", font=ratio_font, fill=MUTED)
    y += 22

    name_font = _font("barlow", 15)
    name_font_bold = _font("barlow", 15, bold=True)

    # Leader
    _draw_banner(d, x, y, inner_w, "Leader", PURPLE)
    y += _banner_height()
    if s.get("leader"):
        d.text((x + 6, y), f"{s['leader']['name']} ({s['leader']['tier']})", font=name_font_bold, fill=PURPLE)
    else:
        d.text((x + 6, y), "Not yet assigned", font=name_font, fill=MUTED)
    y += 22

    # Backup Leader
    _draw_banner(d, x, y, inner_w, "Backup Leader", BACKUP_GRAY)
    y += _banner_height()
    if s.get("backupLeader"):
        d.text((x + 6, y), f"{s['backupLeader']['name']} ({s['backupLeader']['tier']})", font=name_font_bold, fill=TEXT)
    else:
        d.text((x + 6, y), "Not yet assigned", font=name_font, fill=MUTED)
    y += 22

    # Joiners — one name per line, not a comma-wrapped paragraph
    _draw_banner(d, x, y, inner_w, "Joiners", STEEL)
    y += _banner_height()
    joiners = s.get("joiners") or []
    if joiners:
        for p in joiners:
            line = _truncate(d, f"{p['name']} ({p['tier']})", name_font, inner_w - 6)
            d.text((x + 6, y), line, font=name_font, fill=TEXT)
            y += 20
    else:
        d.text((x + 6, y), "Empty - no one assigned yet.", font=name_font, fill=MUTED)
        y += 20

    # Late joiners
    _draw_banner(d, x, y, inner_w, "Late Joiners", GREEN)
    y += _banner_height()
    late = s.get("lateJoiners") or []
    if late:
        for p in late:
            line = _truncate(d, f"{p['name']} ({p['tier']})", name_font, inner_w - 6)
            d.text((x + 6, y), line, font=name_font, fill=MUTED)
            y += 20
    else:
        d.text((x + 6, y), "None added.", font=name_font, fill=MUTED)
        y += 20

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_full_plan(plan):
    """Render every structure side by side in one wide PNG, with a title header. Returns PNG bytes."""
    structures = plan.get("structures", [])
    cards = [_render_card_image(s) for s in structures]
    title_h = 70
    max_card_h = max((c.height for c in cards), default=200)
    total_w = len(cards) * CARD_WIDTH + max(0, len(cards) - 1) * GAP + 2 * PAD
    total_h = title_h + max_card_h + PAD

    img = Image.new("RGB", (total_w, total_h), BG)
    d = ImageDraw.Draw(img)

    title_font = _font("oswald", 26, bold=True)
    sub_font = _font("barlow", 13)
    kingdom = plan.get("kingdomName", "")
    d.text((PAD, 16), f"{kingdom} \u2014 Battle Plan", font=title_font, fill=TEXT)
    import time as _time
    published = plan.get("publishedAt")
    if published:
        stamp = _time.strftime("%Y-%m-%d %H:%M", _time.localtime(published))
        d.text((PAD, 46), f"Published {stamp}", font=sub_font, fill=MUTED)

    cx = PAD
    for card in cards:
        img.paste(card, (cx, title_h))
        cx += CARD_WIDTH + GAP

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _render_card_image(s):
    """Internal: same as render_structure_card but returns a PIL Image, not PNG bytes."""
    png_bytes = render_structure_card(s)
    return Image.open(io.BytesIO(png_bytes))
