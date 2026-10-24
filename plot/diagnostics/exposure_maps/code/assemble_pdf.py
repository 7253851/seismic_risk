"""Assemble the native map, footer and optional statistics as vector content."""
import json
from pathlib import Path
import sys
from pypdf import PdfReader, PdfWriter, Transformation

config = json.loads(Path(sys.argv[1]).read_text())
work = Path(config["work_directory"])
writer = PdfWriter()
page = writer.add_blank_page(width=config["width_inches"] * 72, height=config["height_inches"] * 72)
map_page = PdfReader(work / "building_exposure_BuGn.pdf").pages[0]
scale = config["map_width_inches"] * 72 / float(map_page.mediabox.width)
page.merge_transformed_page(map_page, Transformation().scale(scale).translate(config["map_left_inches"] * 72, config["map_bottom_inches"] * 72))
if config.get("include_statistics", True):
    stats_page = PdfReader(work / "statistical_panels_bcde.pdf").pages[0]
    page.merge_transformed_page(stats_page, Transformation().translate(config["stats_left_inches"] * 72, config["stats_bottom_inches"] * 72))
page.merge_page(PdfReader(work / "panel_a_and_sample_note.pdf").pages[0])
writer.add_metadata({"/Title": "Building exposure: spatial distribution", "/Creator": "Project plotting code; QGIS and Matplotlib", "/Subject": "Stored exposure results; BuGn palette; 53,513 buildings"})
path = work / (config.get("figure_stem", "exposure_map_statistics_abcde") + ".pdf")
with path.open("wb") as handle:
    writer.write(handle)
assert len(PdfReader(path).pages) == 1
print("Composite PDF: " + str(path), flush=True)
