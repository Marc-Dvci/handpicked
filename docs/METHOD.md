# Method and sources

How each number on the page is computed, what it rests on, and how it was measured. Figures are from
`eval/results`; the commands are in the README.

## 1. Finger width from one photo (`handpicked/metrology.py`)

1. **Sheet.** The brightest low-chroma region of the photo is the paper. Its convex hull gives four corners, and a
   line is fitted to each side so a corner stays exact where the wrist covers part of an edge. When the region seems
   to run off the photo (a light grey table can join it), the paper is looked for again among the pixels within 24
   lightness units of the paper's own lightness.
2. **Camera.** The homography from the image to the sheet (A4, 210 × 297 mm) and the
   35 mm-equivalent focal length (EXIF, else 26 mm) give the camera's position above the sheet: height and tilt.
3. **Edges.** MediaPipe Hand Landmarker gives the ring finger's base (landmark 13) and middle joint (14). Profiles
   are cast across the finger every 2% of that span; on each, an edge is where chroma falls fastest going outward,
   which a shadow on the paper or the tint skin reflects onto it do not move. The ring position is the most proximal
   run of seven profiles whose widths agree within 1.2 mm.
4. **Parallax.** The finger's silhouette edges stand above the paper, so the camera's rays through them land wider
   on the sheet. The cross-section is taken as an ellipse with depth 0.95 × width (AIST Hand Dimension Database,
   ring finger at the proximal joint, n = 530; breadth-to-depth ratio about 1.05 at the median), and the width is
   solved so that its two silhouette rays land on the measured edges. Straight above the finger this is the factor
   Z / (Z − h); from the side it also accounts for the flank the camera sees.
5. **Checks.** A photo is refused, with an instruction, when the camera is more than 35° from vertical, the sheet
   gives under 2.5 px per mm (the E1 development benches stayed accurate down to 2.61 px per mm), or the finger's
   edges disagree by more than 1.2 mm along the ring position. A finger joined to its neighbour has no paper edge
   and is refused.

**E1.** `tools/render_bench.py` renders a hand of known finger size on an A4 sheet in Blender with a random camera
height, tilt up to 22°, yaw, focal length, skin tone and table. Two development benches (40 scenes each) were used
to build the method; a third, held-out bench was measured once: 39 of 40 measured, median error 0.05 mm, 90th
percentile 0.10 mm, largest 0.42 mm. The first version had a median of 0.43 mm on the first bench; the held-out
median without the parallax correction is 0.42 mm.

**E2.** The seven sample photos re-encoded (JPEG 60 and 35), rescaled (75%, 150%), rotated (90°, 7°), re-lit
(30% darker, 15% brighter, warmer, lower contrast), defocused and noisy: 81 of 84 measured, median change 0.10 mm,
largest 0.68 mm. This set found the two faults fixed in steps 1 and 5 (a darker photo measured 8.62 mm narrower
without a refusal; a light table taken for paper); before the fixes 75 of 84 were measured.

## 2. Ring size (`handpicked/fit.py`)

The ring's inner diameter is the finger's width (the cross-section is near round, section 1.4), the convention of
Perfect Corp's diamond size chart, which treats US sizes 4, 6 and 8 as fingers 14.9, 16.5 and 18.1 mm wide. US and
EU sizes follow ISO 8653 (inner circumference = 2.55 × US size + 36.5 mm; EU size = circumference in mm). When the
knuckle is more than one size larger, the estimate moves halfway towards the knuckle's size. The range shown spans
the measurement's tolerance.

## 3. Listing reader (`handpicked/listing.py`)

Rules read carat, shape, measurements (L × W × D, round min-max × depth), price and currency, lab, origin, colour and
clarity in grading-report, retailer and marketplace formats in English and French (decimal commas, dot thousands,
"ct"/"carat"/"carats", "mm" with or without spaces). Every value keeps its character span. Instruction-like text
("ignore previous instructions", "SYSTEM:", French equivalents) is masked before any reader sees the listing. A
price inside an instalment, a "from" price or a setting price is not the stone's price. Moissanite, simulants,
cubic zirconia, sapphire, spinel, topaz and zircon wait outside the board; so do shapes outside the eight.

The model (Alibaba Cloud Model Studio, `deepseek-v4.1-flash-1017`, thinking off) is asked only for the fields the
rules left empty. Each value it returns must come with a quote that occurs in the listing, outside masked text, and
whose numbers parse to that value under the same price rules; anything else is dropped and named on the page.

**E4.** 60 listings in six formats were written and labelled, and the corpus committed, before the reader was
scored; 30 are held out and were read once. Held-out: 98.0% of 300 fields correct, 0 wrong numbers on the board, 3 of
3 injected instructions ignored. The first held-out run with the model had 2 wrong prices (a "from" price and a
setting price the model quoted); the model's quotes now pass the price rules, and the corrected run is 98.0% with
0 wrong. Ten free-text listings ("8.1 by 5.6 by 3.4 mm", "a touch under a carat (0.92 ct)"): rules alone 77% and 0
stones on the board; rules and model 85% and 7 of 10, with 0 wrong numbers.

## 4. Board (`handpicked/compare.py`, `handpicked/gems.py`, `handpicked/weights.py`)

- **Face-up area** from the girdle outline of each shape (`outlines.py`, the same outlines the ring renders use),
  scaled to the listed length and width.
- **Coverage** is the stone's width across the finger (set north-south) divided by the measured finger width.
- **Price per mm²** ranks the board; stones without a price are shown unranked.
- **Spread** compares the face-up area with a typical well-cut stone of the same shape and weight, interpolated
  log-log in Perfect Corp's diamond size chart (13 Oct 2026); a deep stone that hides weight shows negative spread.
- **Weight from mm** uses the diamond weight factors of Omni Calculator's diamond weight calculator, cross-checked
  against the International Gem Society's formulas; a listed weight more than 12% from it is flagged.
- **Look-alike pair:** two stones of one shape within 0.2 mm across the finger and 6% in area whose prices differ by
  more than 10%.
- **Round weight:** natural stones at 0.50, 0.70, 1.00, 1.50, 2.00 or 3.00 ct (up to +0.05) are flagged. On
  PriceScope's natural round grid the median matched-cell step from 0.90-0.99 to 1.00-1.19 ct is +23.9% per carat
  (74 cells); on the lab-grown grid it is +4.0% (32 cells), so lab-grown stones are not flagged.
- **Verdict:** a template sentence from the facts. The model may reword it; the reworded sentence is shown only if
  it keeps every number of the template, adds none that is not in the facts, has no exclamation mark and stays
  under 60 words.

**E5.** 144 shortlists built from PriceScope's October 2026 cell averages and the size chart's typical dimensions
(section 4 of the README).

## 5. Size-true try-on (`handpicked/library.py`, `handpicked/audit.py`, `handpicked/service.py`)

Measured on the Ring VTO (`spike/` notes, then E3): the engine maps the anchor points, the band's inner edge in the
product image, to the finger, and draws the band about 1.15 times the finger's width; the stone keeps its proportion
to the band. So the drawn stone width is

    stone / finger = c_shape × product ratio × band fit

where the product ratio is stone width ÷ band outer diameter in the ring image, the band fit is the band's drawn
width ÷ the finger's width, and c_shape is a constant per shape. `tools/render_rings.py` renders 432 solitaires on an
orthographic camera, so every length in the image is exact: 8 shapes × 2 metals × ratios 0.16 to 0.68 in steps of
0.02. For a request, the library picks the render closest to target ÷ (c_shape × band fit) and scales the anchor
points by at most 6% for the rest.

**E3.** Calibration rings carry a flat green stone. 204 live calls on the sample hands (round, oval, pear and
emerald at 5 ratios on 7 hands; cushion, princess, radiant and marquise at 4 ratios on 4 hands): the green width in
the render divided by the finger width is the observed ratio, and the band's footprint (the pixels the try-on
changed, across the finger) is the band fit in that render. c_shape fitted on the other hands and scored on the hand
left out: median error 1.11%, 90th percentile 3.25%, 193 of 197 within 5%. One product photo for every stone size
would be off by up to 67%.

**Audit.** Every production render is measured the same way through its band; if the stone it implies is more than
5% from the target, the ring is re-chosen with the band fit that render showed and rendered once more. For an
uploaded hand the band fit starts at the median of the sample hands (1.152) and is replaced by the one measured in
its first render.

## 6. Sources

| Ref | Source | Used for |
|---|---|---|
| Perfect Corp | "Diamond Size Chart: How Big Does 0.5 to 3 Carats Really Look?", 13 Oct 2026, https://www.perfectcorp.com/business/blog/general/diamond-size-chart | Typical dimensions per shape and weight; finger widths for US sizes 4, 6, 8; "a 1 ct round covers 39% of a size 6 finger" |
| YouCam API | Ring Virtual Try-On reference, https://docs.perfectcorp.com/reference/ring_vto | Parameters `ring_wearing_finger`, `ring_wearing_location`, `ring_anchor_point`; 1 unit per render |
| ISO 8653 | Jewellery: ring sizes, definition, measurement and designation | Size from inner circumference |
| AIST | AIST Digital Human Research Team, Hand Dimension Database, https://www.airc.aist.go.jp/dhrt/hand/index.html (items B10 and D06) | Finger depth 0.95 × width at the ring position |
| PriceScope | Natural and lab-grown diamond price charts, fetched 24 Oct 2026, latest column October 2026, https://pricescope.com/diamond-prices/round (and oval, pear, princess, radiant; lab-grown round) | Sample prices, the jeweller feed, E5, the round-weight step. Cell averages for average cut quality; extract in `eval/prices/pricescope_cells_2026-10.csv` |
| S3 | Omni Calculator, Diamond Weight Calculator, https://www.omnicalculator.com/other/diamond-weight | Weight factors per shape and length-to-width ratio |
| S1 | International Gem Society, "How to Estimate Gem Weight in a Jewelry Setting", https://www.gemsociety.org/article/estimating-gem-weight | Cross-check of the weight factors |
| MediaPipe | Hand Landmarker (`assets/models/hand_landmarker.task`) | Ring finger landmarks |
