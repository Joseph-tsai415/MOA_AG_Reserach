# PBL report figures

Helpers are in `scripts/pbl_figures.py` (`canvas`, `box`, `arrow`, `edge_label`). Also follow the `dataviz` skill, and run its palette validator.

## Rules for every figure

- Set `figsize` to the print size, so a font size in code is the printed point size. For A4 with 2 cm margins use 6.6 in wide.
- Keep all text at 8 pt or larger, and node text at 8.5 pt or larger.
- Render, read the PNG back, then read the placed page. Check for overlaps, clipped text and missing CJK glyphs.
- Export at 300 dpi. Check that any pasted image has at least 150 dpi at its embed size.
- Give each causal idea one figure. A figure must show something the tables do not.
- State the finding in the title where the figure has one. Number, caption and credit every figure.
- Redraw rather than paste, and cite the data source.
- Every factual label must already be supported by the evidence ledger, and every edge is a claim too. A link no source supports stays undrawn. Use a "may" style for possible links, and a dashed box for a finding with no known mechanism.
- Mark schematic curves as schematic, and keep a numeric axis off them.
- Two measures on different scales need two panels, never two y-axes.
- Keep table rows whole and never strand a header row. `scripts/pbl_docx.py` handles this.

## Default figure set

| Figure | Job | Form |
|---|---|---|
| Concept map | The whole case on one page | Swimlanes, below |
| Physiology chain | How the disease classes fail in a shared pathway | Left-to-right columns, below |
| Episode timeline | Which symptom belongs to which stage | Shaded columns, below |
| Time or threshold figure | What a test could and could not see | `broken_barh` time windows, or bullet bars against thresholds |
| Case image | Show the reading method | The image, with marks and a zoomed inset |

Choose by what the case needs. Skip any that would only repeat a table.

## Concept map: swimlanes

Portrait, 6.6 × 8.5 in, full page, at most 30 nodes. Use horizontal lanes with labels in a left gutter, and a light tint per lane with dark text.

| Lane | Contents |
|---|---|
| Triggers | Case triggers, one node each |
| Mechanism | A left-to-right chain from first event to final common pathway. Any less-understood route gets a dashed border and says so |
| Case findings | Symptoms and signs |
| Differential | One chip per diagnosis, naming the finding or test that argues against it |
| Next steps | Conclusion bar, next test, management, psychosocial thread, red-flag box |

The mechanism-to-findings edges are the point of the figure.

Order the findings lane so edges fan out without crossing. Print a verb on the edges, and use one style per meaning:

| Style | Meaning |
|---|---|
| Black solid | causes |
| Black dash-dot | may cause |
| Blue thick | supports |
| Grey dashed | argues against |
| Orange dotted | not excluded |

Put ①②③ badges on case nodes to show which act they came from. Leave a gap through the differential lane so the supporting arrow reaches the conclusion without crossing chips.

## Physiology chain

6.6 × 3.25 in. Columns: disease classes, the physiological determinants, the shared intermediate, the end-organ result. Give each class its own arrow colour, and draw this case's path thick. Print the key thresholds under the final column.

## Episode timeline

6.6 × 3.4 in. Shaded columns for each stage, with a non-linear x-axis stated in the caption. Top row: schematic curves labelled 示意圖，非本案量測. Middle row: case symptoms. Bottom row: the physiological step. Size the columns to their text.

## Time-window figure

6.6 × 2.85 in. Use `broken_barh`, one row per criterion or test, with a vertical line where the test ended and a marker where the event happened. A narrow right panel can show bullet bars of each measured change against its threshold.

## Case image

Stack the image over a zoomed inset. Mark the measurements on the image, label the waves or features in the inset, and state that the marks are yours and not machine measurements.
