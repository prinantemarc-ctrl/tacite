"""Génère le monogramme Tacite : parchemin gravé dans la fratrie exacte d'Acheron,
Gorgone et Hannibal (même tuile squircle macOS sombre biseautée, même échelle de
glyphe x=58..197 / 256, même dégradé blanc → argent fumé 255 → 180).

Composition du glyphe (repère 0–64) :
- une vraie feuille de parchemin déployée (haut et bas s'enroulent en deux
  cylindres à spirales latérales, flancs souples en S parallèle) ;
- un grand calame / plume d'argent qui traverse le parchemin en diagonale, plus
  un second stylet fin croisé ;
- trois sillons d'écriture manuscrite gravés en négatif au cœur de la feuille.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw


def cubic(p0, p1, p2, p3, n=48):
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def chain(segments):
    out = []
    for i, seg in enumerate(segments):
        out.extend(seg if i == 0 else seg[1:])
    return out


def sample_stroke(center_pts, w_fn):
    n = len(center_pts)
    left, right = [], []
    for i, (x, y) in enumerate(center_pts):
        t = i / max(1, n - 1)
        if i == 0:
            dx, dy = center_pts[1][0] - x, center_pts[1][1] - y
        elif i == n - 1:
            dx, dy = x - center_pts[i - 1][0], y - center_pts[i - 1][1]
        else:
            dx, dy = center_pts[i + 1][0] - center_pts[i - 1][0], center_pts[i + 1][1] - center_pts[i - 1][1]
        L = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / L, dx / L
        hw = w_fn(t) * 0.5
        left.append((x + nx * hw, y + ny * hw))
        right.append((x - nx * hw, y - ny * hw))
    return left + list(reversed(right))


# --- Géométrie du parchemin (repère 0–64) ---
# Pourquoi on reconnaît immédiatement un parchemin :
# 1) Le rouleau du haut et le rouleau du bas sont continus avec la feuille : la
#    feuille monte, s'enroule vers l'avant en haut (avec l'ouverture en goutte
#    sur le côté droit et la lèvre horizontale qui projette une ombre franche
#    sur la feuille), et en bas s'enroule en sens inverse avec l'ouverture en
#    goutte sur le côté gauche + un bord inférieur légèrement dentelé.
# 2) Les deux bords latéraux de la feuille sont en S parallèle (largeur pleine,
#    jamais pincée en sablier).
# 3) Deux couples de fins stylets croisés traversent derrière la feuille comme
#    sur Acheron.


def glyph_layers():
    ops = []

    def add(poly):
        ops.append(("add", poly))

    def cut(poly):
        ops.append(("cut", poly))

    # 1. Arrière-plan : les verges / stylets fins croisés en X (signature de la fratrie)
    for (p0, p1, w_max) in [
        ((7.5, 9.5), (56.5, 54.5), 1.35),
        ((12.0, 7.2), (58.0, 50.2), 0.90),
        ((56.5, 9.5), (7.5, 54.5), 1.35),
        ((52.0, 7.2), (6.0, 50.2), 0.90),
    ]:
        line = cubic(
            p0,
            ((p0[0] * 2 + p1[0]) / 3, (p0[1] * 2 + p1[1]) / 3),
            ((p0[0] + p1[0] * 2) / 3, (p0[1] + p1[1] * 2) / 3),
            p1,
            36,
        )
        add(sample_stroke(line, lambda t, wm=w_max: 0.14 + wm * math.sin(math.pi * t)))

    # 2. Réserve noire autour du parchemin pour détacher les stylets du corps
    halo = chain([
        cubic((14.0, 8.8), (26.0, 7.6), (40.0, 7.6), (51.5, 9.6), 24),
        cubic((51.5, 9.6), (56.2, 11.4), (56.0, 21.0), (49.2, 22.8), 20),
        cubic((49.2, 22.8), (46.0, 30.0), (49.8, 37.0), (48.0, 42.2), 28),
        cubic((48.0, 42.2), (52.5, 43.8), (52.2, 52.8), (47.0, 54.6), 20),
        cubic((47.0, 54.6), (37.0, 56.4), (23.0, 56.4), (12.8, 54.4), 24),
        cubic((12.8, 54.4), (8.0, 52.6), (8.2, 43.0), (15.0, 41.2), 20),
        cubic((15.0, 41.2), (18.2, 34.0), (14.4, 27.0), (16.2, 21.6), 28),
        cubic((16.2, 21.6), (11.5, 20.0), (11.5, 10.6), (14.0, 8.8), 20),
    ])
    cut(halo)

    # 3. Silhouette unifiée du parchemin déroulé :
    #    - rouleau supérieur (y ≈ 10.2..21.2, x ≈ 13.5..53.5) ;
    #    - feuille déroulée en S parallèle (x ≈ 17.5..46.5, y ≈ 21.2..42.8) ;
    #    - rouleau inférieur (y ≈ 42.8..53.8, x ≈ 10.5..50.5).
    parchment = chain([
        # Crête supérieure du rouleau du haut (légèrement cambrée)
        cubic((15.4, 11.2), (25.0, 9.4), (40.5, 9.4), (50.2, 11.4), 32),
        # Bout droit du rouleau supérieur (le tambour où l'on verra la spirale)
        cubic((50.2, 11.4), (54.4, 12.6), (54.4, 20.0), (49.6, 21.2), 24),
        # Rentrée sous le tambour droit vers le bord droit de la feuille
        cubic((49.6, 21.2), (48.0, 21.6), (46.8, 21.8), (45.8, 22.0), 12),
        # Bord droit de la feuille : belle onde en S de parchemin souple
        cubic((45.8, 22.0), (42.8, 28.8), (48.2, 35.6), (46.2, 42.2), 36),
        # Sortie vers le bout droit du rouleau inférieur
        cubic((46.2, 42.2), (47.4, 42.4), (48.6, 42.8), (49.6, 43.4), 12),
        # Bout droit du rouleau inférieur
        cubic((49.6, 43.4), (52.0, 44.8), (51.8, 51.0), (48.6, 52.6), 24),
        # Crête inférieure du rouleau du bas
        cubic((48.6, 52.6), (39.0, 54.6), (23.5, 54.6), (13.8, 52.6), 32),
        # Bout gauche du rouleau inférieur (tambour gauche)
        cubic((13.8, 52.6), (9.6, 51.4), (9.6, 44.0), (14.4, 42.8), 24),
        # Rentrée au-dessus du tambour gauche vers le bord gauche de la feuille
        cubic((14.4, 42.8), (16.0, 42.4), (17.2, 42.2), (18.2, 42.0), 12),
        # Bord gauche de la feuille : onde en S strictement parallèle au bord droit
        cubic((18.2, 42.0), (20.2, 35.6), (14.8, 28.8), (17.8, 21.8), 36),
        # Sortie vers le bout gauche du rouleau supérieur
        cubic((17.8, 21.8), (16.6, 21.6), (15.4, 21.2), (14.4, 20.6), 12),
        # Bout gauche du rouleau supérieur
        cubic((14.4, 20.6), (12.0, 19.2), (12.2, 13.0), (15.4, 11.2), 24),
    ])
    add(parchment)

    # 4. Les deux bâtons de parchemin (umbilici) qui sortent des tambours :
    #    deux traits effilés à chaque bout, comme les ailettes de Gorgone.
    for (x0, y0, x1, y1, w0) in [
        # Haut-droite
        (52.0, 15.2, 58.6, 14.4, 1.25),
        (52.0, 17.4, 57.0, 18.2, 0.95),
        # Haut-gauche
        (13.2, 15.2, 7.2, 14.4, 1.10),
        (13.2, 17.4, 8.6, 18.2, 0.85),
        # Bas-gauche
        (12.0, 46.6, 5.4, 45.8, 1.25),
        (12.0, 48.8, 7.0, 49.6, 0.95),
        # Bas-droite
        (50.8, 46.6, 56.8, 45.8, 1.10),
        (50.8, 48.8, 55.4, 49.6, 0.85),
    ]:
        rod = cubic((x0, y0), ((x0 * 2 + x1) / 3, (y0 * 2 + y1) / 3),
                    ((x0 + x1 * 2) / 3, (y0 + y1 * 2) / 3), (x1, y1), 18)
        add(sample_stroke(rod, lambda t, w=w0: w * (1 - t * 0.85)))

    # 5. Gravures noires qui dessinent les deux rouleaux et leur spirale :
    #    a) Lèvre inférieure du rouleau du haut : une courbe noire franche qui
    #       part du bord gauche, longe tout le dessous du rouleau et s'enroule
    #       en spirale dans le tambour droit !
    top_lip_and_spiral = chain([
        cubic((13.8, 20.4), (24.0, 19.0), (39.0, 19.0), (48.2, 20.2), 32),
        # Remonte dans le tambour droit pour former la volute du parchemin
        cubic((48.2, 20.2), (52.0, 19.6), (52.2, 13.6), (48.4, 13.0), 24),
        cubic((48.4, 13.0), (45.2, 12.8), (44.8, 17.6), (48.0, 17.8), 24),
        cubic((48.0, 17.8), (49.8, 17.8), (50.0, 15.4), (48.4, 15.2), 18),
    ])
    cut(sample_stroke(top_lip_and_spiral, lambda t: 1.55 * (1.0 - 0.38 * t)))

    # Sillon de pli sur le dessus du rouleau supérieur
    top_seam = cubic((16.5, 14.8), (26.0, 13.4), (38.0, 13.4), (44.2, 14.6), 28)
    cut(sample_stroke(top_seam, lambda t: 0.25 + 1.05 * math.sin(math.pi * t)))

    #    b) Lèvre supérieure du rouleau du bas : symétrique inversée (part de la
    #       droite, longe le dessus du rouleau inférieur et s'enroule en spirale
    #       dans le tambour gauche !)
    bot_lip_and_spiral = chain([
        cubic((50.2, 43.6), (40.0, 45.0), (25.0, 45.0), (15.8, 43.8), 32),
        cubic((15.8, 43.8), (12.0, 44.4), (11.8, 50.4), (15.6, 51.0), 24),
        cubic((15.6, 51.0), (18.8, 51.2), (19.2, 46.4), (16.0, 46.2), 24),
        cubic((16.0, 46.2), (14.2, 46.2), (14.0, 48.6), (15.6, 48.8), 18),
    ])
    cut(sample_stroke(bot_lip_and_spiral, lambda t: 1.55 * (1.0 - 0.38 * t)))

    bot_seam = cubic((47.5, 49.2), (38.0, 50.6), (26.0, 50.6), (19.8, 49.4), 28)
    cut(sample_stroke(bot_seam, lambda t: 0.25 + 1.05 * math.sin(math.pi * t)))

    # 6. Sur la feuille de parchemin : trois sillons d'écriture calligraphiée
    #    (ondulent avec la feuille) + une entaille latérale de vieux parchemin
    for y0, x0, x1 in [
        (26.4, 21.8, 42.0),
        (31.8, 21.2, 42.6),
        (37.2, 22.0, 37.6),
    ]:
        line = cubic((x0, y0), (x0 + 5.5, y0 - 1.1), (x1 - 5.5, y0 + 0.9), (x1, y0 - 0.2), 28)
        cut(sample_stroke(line, lambda t: 0.30 + 1.35 * math.sin(math.pi * t)))

    # Petite brèche triangulaire d'usure sur le flanc droit et gauche de la feuille
    cut([(46.2, 31.0), (41.8, 32.2), (46.0, 33.2)])
    cut([(17.2, 28.2), (21.4, 29.2), (17.0, 30.4)])

    return ops


def render_mask(size: int, pad_ratio: float = 0.175) -> Image.Image:
    ss = 4
    big = size * ss
    pad = big * pad_ratio
    scale = (big - 2 * pad) / 64.0

    def tr(pts):
        return [(x * scale + pad, y * scale + pad) for x, y in pts]

    mask = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(mask)
    for mode, poly in glyph_layers():
        draw.polygon(tr(poly), fill=255 if mode == "add" else 0)
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def squircle_plate(size: int) -> Image.Image:
    ref = Path("/tmp/ref-plate-256.png")
    if ref.exists():
        base = Image.open(ref).convert("RGBA")
        if base.size != (size, size):
            base = base.resize((size, size), Image.Resampling.LANCZOS)
        return base

    ss = 4
    big = size * ss
    margin = int(big * 0.09765)
    radius = int((big - 2 * margin) * 0.2237)

    alpha = Image.new("L", (big, big), 0)
    ad = ImageDraw.Draw(alpha)
    ad.rounded_rectangle((margin, margin, big - 1 - margin, big - 1 - margin), radius=radius, fill=255)
    alpha = alpha.resize((size, size), Image.Resampling.LANCZOS)

    out = Image.new("RGBA", (size, size), (10, 10, 10, 255))
    out.putalpha(alpha)
    return out


def metallic_ink_layer(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size))
    px = img.load()
    y0, y1 = size * 0.24, size * 0.76
    for y in range(size):
        t = max(0.0, min(1.0, (y - y0) / max(1.0, y1 - y0)))
        v = int(round(255 - 83 * (t ** 1.15)))
        for x in range(size):
            px[x, y] = (v, v, v, 255)
    return img


def raster_icon(size: int = 1024) -> Image.Image:
    plate = squircle_plate(size)
    glyph = render_mask(size, pad_ratio=0.175)
    ink = metallic_ink_layer(size)
    return Image.composite(ink, plate, glyph)


def raster_mark(size: int = 512) -> Image.Image:
    glyph = render_mask(size, pad_ratio=0.04)
    ink = metallic_ink_layer(size)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return Image.composite(ink, out, glyph)


def poly_to_svg_d(poly) -> str:
    head = f"M{poly[0][0]:.2f} {poly[0][1]:.2f}"
    tail = " ".join(f"L{x:.2f} {y:.2f}" for x, y in poly[1:])
    return f"{head} {tail}Z"


def svg_mask_elements() -> str:
    lines = ['      <rect width="64" height="64" fill="#000"/>']
    for mode, poly in glyph_layers():
        fill = "#fff" if mode == "add" else "#000"
        lines.append(f'      <path fill="{fill}" d="{poly_to_svg_d(poly)}"/>')
    return "\n".join(lines)


def write_svgs(public: Path):
    mask_inner = svg_mask_elements()
    (public / "logo.svg").write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
  <defs>
    <linearGradient id="tacite-ink" x1="32" y1="8" x2="32" y2="56" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="52%" stop-color="#d7d7d7"/>
      <stop offset="100%" stop-color="#acacac"/>
    </linearGradient>
    <linearGradient id="tacite-rim" x1="32" y1="0" x2="32" y2="64" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#787879" stop-opacity="0.72"/>
      <stop offset="35%" stop-color="#3a3a3c" stop-opacity="0.35"/>
      <stop offset="100%" stop-color="#1c1c1e" stop-opacity="0.2"/>
    </linearGradient>
    <mask id="tacite-glyph">
{mask_inner}
    </mask>
  </defs>
  <rect width="64" height="64" rx="14.3" fill="#0a0a0a"/>
  <rect x="0.5" y="0.5" width="63" height="63" rx="13.8" stroke="url(#tacite-rim)" stroke-width="1"/>
  <rect width="64" height="64" fill="url(#tacite-ink)" mask="url(#tacite-glyph)"/>
</svg>
''',
        encoding="utf-8",
    )
    (public / "logo-mark.svg").write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
  <defs>
    <mask id="tacite-glyph">
{mask_inner}
    </mask>
  </defs>
  <rect width="64" height="64" fill="currentColor" mask="url(#tacite-glyph)"/>
</svg>
''',
        encoding="utf-8",
    )


def build_icns(icon_png: Path, icns_out: Path):
    iconset = icns_out.parent / "icon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)
    src = Image.open(icon_png)
    for base in (16, 32, 128, 256, 512):
        src.resize((base, base), Image.Resampling.LANCZOS).save(iconset / f"icon_{base}x{base}.png")
        src.resize((base * 2, base * 2), Image.Resampling.LANCZOS).save(
            iconset / f"icon_{base}x{base}@2x.png"
        )
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns_out)], check=True)
    shutil.rmtree(iconset)


def main():
    frontend_root = Path(__file__).resolve().parents[1]
    repo_root = frontend_root.parent
    public = frontend_root / "public"
    desktop_build = repo_root / "desktop" / "build"
    public.mkdir(exist_ok=True)

    write_svgs(public)
    icon = raster_icon(1024)
    mark = raster_mark(512)
    icon.save(public / "logo.png")
    mark.save(public / "logo-mark.png")
    icon.resize((180, 180), Image.Resampling.LANCZOS).save(public / "apple-touch-icon.png")
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(public / "logo-preview.png")

    if desktop_build.exists():
        icon.save(desktop_build / "icon.png")
        build_icns(desktop_build / "icon.png", desktop_build / "icon.icns")

    ts_out = frontend_root / "src" / "components" / "taciteGlyph.ts"
    entries = [
        f'  ["{"#fff" if mode == "add" else "#000"}", "{poly_to_svg_d(poly)}"],'
        for mode, poly in glyph_layers()
    ]
    ts_out.write_text(
        "// Auto-generated by frontend/scripts/build_logo.py — do not edit by hand.\n"
        "export const TACITE_GLYPH_OPS: readonly [string, string][] = [\n"
        + "\n".join(entries)
        + "\n];\n",
        encoding="utf-8",
    )

    print("ops:", len(glyph_layers()))
    print("wrote", public / "logo.svg", desktop_build / "icon.png", desktop_build / "icon.icns")


if __name__ == "__main__":
    main()
