"""Regenerate the original NEXUS N/node favicon family (Pillow, development only)."""
from pathlib import Path

from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1] / "apps/web/public"
root.mkdir(parents=True, exist_ok=True)
svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#0d0f15"/><path d="M18 46V18L46 46V18" fill="none" stroke="#aaa3ff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/><circle cx="46" cy="18" r="4" fill="#83d5b3"/></svg>\n'
(root / "icon.svg").write_text(svg, encoding="utf-8")
scale = 16
canvas = Image.new("RGBA", (64 * scale, 64 * scale))
draw = ImageDraw.Draw(canvas)
draw.rounded_rectangle((0, 0, 64*scale-1, 64*scale-1), radius=16*scale, fill="#0d0f15")
points = [(18*scale,46*scale),(18*scale,18*scale),(46*scale,46*scale),(46*scale,18*scale)]
draw.line(points, fill="#aaa3ff", width=6*scale, joint="curve")
for x,y in points:
    draw.ellipse((x-3*scale,y-3*scale,x+3*scale,y+3*scale),fill="#aaa3ff")
draw.ellipse((42*scale,14*scale,50*scale,22*scale),fill="#83d5b3")
for size,name in [(16,"favicon-16x16.png"),(32,"favicon-32x32.png"),(180,"apple-touch-icon.png"),(192,"nexus-192.png"),(512,"nexus-512.png")]:
    image=canvas.resize((size,size),Image.Resampling.LANCZOS)
    if size==180:
        opaque=Image.new("RGB",image.size,"#0d0f15");opaque.paste(image,mask=image.getchannel("A"));image=opaque
    image.save(root/name)
canvas.save(root/"favicon.ico",format="ICO",sizes=[(16,16),(32,32),(48,48),(64,64)])
print("Created SVG, four-size ICO, 16/32px PNG, Apple and 192/512px icons.")
