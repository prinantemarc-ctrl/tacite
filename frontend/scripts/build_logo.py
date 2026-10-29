"""Génère le monogramme Tacite : parchemin stylisé, même langage que les icônes bateau / archer."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# Repère de dessin : 0–64, glyphe centré. Même chemin pour SVG et raster.
# Courbes tendues, pointes nettes, symétrie verticale — un parchemin réduit
# à deux rouleaux en losange et une feuille légèrement cintrée.


def cubic(p0, p1, p2, p3, n=40):
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def mirror_x(pts, cx=32.0):
    return [(2 * cx - x, y) for x, y in pts]


def chain(segments):
    out = []
    for i, seg in enumerate(segments):
        out.extend(seg if i == 0 else seg[1:])
    return out


# --- Silhouette (quart supérieur droit, puis miroirs) ---
# Sommet, corne droite, pointe du rouleau, raccord feuille, taille.

def outer_path():
    # De la pointe haute vers la taille, côté droit, en cubiques.
    # Rouleaux larges et pointus, feuille presque aussi large — un parchemin,
    # pas un sablier.
    top_peak = (32.0, 5.8)
    right_horn = (50.2, 11.6)
    right_tip = (57.2, 18.4)
    roll_under = (46.4, 24.6)
    waist = (44.2, 32.0)

    down = chain([
        cubic(top_peak, (36.8, 5.6), (44.0, 8.8), right_horn),
        cubic(right_horn, (54.6, 13.8), (58.4, 16.0), right_tip),
        cubic(right_tip, (55.6, 21.4), (50.8, 23.6), roll_under),
        cubic(roll_under, (45.2, 26.4), (44.4, 28.8), waist),
    ])
    # Miroir vertical autour de y=32 pour la moitié basse droite
    up_rev = [(x, 64.0 - y) for x, y in reversed(down[:-1])]  # waist déjà en 32
    right = down + up_rev
    # Miroir horizontal, en remontant
    left = mirror_x(list(reversed(right[1:-1])))
    return right + left


def almond(cx, cy, rx=7.6, ry=2.7, n=48):
    """Trou en amande, pointes à gauche/droite — le creux du rouleau."""
    # Deux cubiques haut / bas
    left, right = (cx - rx, cy), (cx + rx, cy)
    top = cubic(left, (cx - rx * 0.35, cy - ry), (cx + rx * 0.35, cy - ry), right, n // 2)
    bot = cubic(right, (cx + rx * 0.35, cy + ry), (cx - rx * 0.35, cy + ry), left, n // 2)
    return top + bot[1:]


def path_d(pts, closed=True):
    cmds = [f"M {pts[0][0]:.2f} {pts[0][1]:.2f}"]
    # On réécrit en cubiques trop verbeux ; polyline lissée suffit en SVG
    # si on émet les cubiques sources. Ici on approxime en L pour le raster
    # et on reconstruit les cubiques pour le SVG ci-dessous.
    for x, y in pts[1:]:
        cmds.append(f"L {x:.2f} {y:.2f}")
    if closed:
        cmds.append("Z")
    return " ".join(cmds)


def svg_mark_d():
    """Chemin SVG exact (cubiques), fill-rule evenodd."""
    # Identique à outer_path / almond, écrit en C.
    return (
        "M32 5.8 "
        "C36.8 5.6 44 8.8 50.2 11.6 "
        "C54.6 13.8 58.4 16 57.2 18.4 "
        "C55.6 21.4 50.8 23.6 46.4 24.6 "
        "C45.2 26.4 44.4 28.8 44.2 32 "
        "C44.4 35.2 45.2 37.6 46.4 39.4 "
        "C50.8 40.4 55.6 42.6 57.2 45.6 "
        "C58.4 48 54.6 50.2 50.2 52.4 "
        "C44 55.2 36.8 58.4 32 58.2 "
        "C27.2 58.4 20 55.2 13.8 52.4 "
        "C9.4 50.2 5.6 48 6.8 45.6 "
        "C8.4 42.6 13.2 40.4 17.6 39.4 "
        "C18.8 37.6 19.6 35.2 19.8 32 "
        "C19.6 28.8 18.8 26.4 17.6 24.6 "
        "C13.2 23.6 8.4 21.4 6.8 18.4 "
        "C5.6 16 9.4 13.8 13.8 11.6 "
        "C20 8.8 27.2 5.6 32 5.8 Z "
        # trou haut
        "M23.6 18.4 "
        "C26.2 15.8 28.8 15.8 32 15.8 "
        "C35.2 15.8 37.8 15.8 40.4 18.4 "
        "C37.8 21 35.2 21 32 21 "
        "C28.8 21 26.2 21 23.6 18.4 Z "
        # trou bas
        "M23.6 45.6 "
        "C26.2 43 28.8 43 32 43 "
        "C35.2 43 37.8 43 40.4 45.6 "
        "C37.8 48.2 35.2 48.2 32 48.2 "
        "C28.8 48.2 26.2 48.2 23.6 45.6 Z"
    )


def rounded_rect_mask(size: int, radius: float) -> Image.Image:
    """Superellipse approchée (iOS-like) via rounded rect + anti-alias."""
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return m


def scale_pts(pts, s, ox=0.0, oy=0.0):
    return [(x * s + ox, y * s + oy) for x, y in pts]


def raster_icon(size=1024) -> Image.Image:
    # Fond transparent, squircle noir, glyphe blanc
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    radius = size * 0.2237
    mask = rounded_rect_mask(size, radius)
    black = Image.new("RGBA", (size, size), (10, 10, 10, 255))
    img = Image.composite(black, img, mask)

    # Glyphe : 64-unit → zone intérieure (marge ~18 %)
    pad = size * 0.16
    s = (size - 2 * pad) / 64.0
    draw = ImageDraw.Draw(img)
    outer = scale_pts(outer_path(), s, pad, pad)
    draw.polygon(outer, fill=(255, 255, 255, 255))
    for cy in (18.4, 45.6):
        hole = scale_pts(almond(32.0, cy, rx=8.4, ry=2.6), s, pad, pad)
        draw.polygon(hole, fill=(10, 10, 10, 255))
    # Re-clip corners
    img.putalpha(Image.composite(img.split()[-1], Image.new("L", (size, size), 0), mask))
    return img


def raster_mark(size=1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    s = size / 64.0
    draw = ImageDraw.Draw(img)
    draw.polygon(scale_pts(outer_path(), s), fill=(255, 255, 255, 255))
    for cy in (18.4, 45.6):
        draw.polygon(scale_pts(almond(32.0, cy, rx=8.4, ry=2.6), s), fill=(0, 0, 0, 0))
    # Les trous en alpha 0 : PIL polygon transparent ne perce pas. Masque even-odd.
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.polygon(scale_pts(outer_path(), s), fill=255)
    for cy in (18.4, 45.6):
        md.polygon(scale_pts(almond(32.0, cy, rx=8.4, ry=2.6), s), fill=0)
    out = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    out.putalpha(mask)
    return out


def write_svg_icon(path: Path):
    d = svg_mark_d()
    path.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
  <rect width="64" height="64" rx="14.3" fill="#0a0a0a"/>
  <path fill="#fff" fill-rule="evenodd" d="{d}"/>
</svg>
''',
        encoding="utf-8",
    )


def write_svg_mark(path: Path):
    d = svg_mark_d()
    path.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
  <path fill="currentColor" fill-rule="evenodd" d="{d}"/>
</svg>
''',
        encoding="utf-8",
    )


def ascii_preview(img: Image.Image, n=40):
    img = img.convert("L").resize((n, n), Image.Resampling.BILINEAR)
    chars = " .:-=+*#%@"
    rows = []
    for y in range(n):
        row = []
        for x in range(n):
            v = img.getpixel((x, y))
            row.append(chars[min(len(chars) - 1, v * len(chars) // 256)])
        rows.append("".join(row))
    return "\n".join(rows)


def main():
    root = Path(__file__).resolve().parents[1]
    public = root / "public"
    public.mkdir(exist_ok=True)
    write_svg_icon(public / "logo.svg")
    write_svg_mark(public / "logo-mark.svg")
    icon = raster_icon(1024)
    mark = raster_mark(1024)
    icon.save(public / "logo.png")
    mark.save(public / "logo-mark.png")
    preview = raster_icon(256)
    preview.save(public / "logo-preview.png")
    print(ascii_preview(icon))
    print("wrote", public / "logo.svg", public / "logo.png")


if __name__ == "__main__":
    main()
