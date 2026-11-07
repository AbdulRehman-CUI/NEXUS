"""Generate small demo files. Run from the repository root using the API environment."""

from pathlib import Path

import pymupdf

root = Path(__file__).resolve().parents[1] / "examples"
root.mkdir(exist_ok=True)
pdf = pymupdf.open()
for text in [
    "AURORA / LAUNCH BRIEF\nAurora launches on 14 November 2026.\nMira is the launch owner.",
    "AURORA / READINESS\nThe launch review is on 12 November 2026.\nThe launch requires approval from the review owner.",
]:
    page = pdf.new_page()
    page.insert_text((72, 72), text, fontsize=14)
pdf.save(root / "aurora-brief.pdf")
pdf.close()
print(f"Demo PDF ready: {root / 'aurora-brief.pdf'}")
