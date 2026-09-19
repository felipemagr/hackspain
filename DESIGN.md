# Design

The visual system of the X Ray demo (`web/`). Product truth lives in `PRODUCT.md`; this file
records what the built UI does so later screens follow it instead of inventing a new look.

## Principles

1. One group, one curve. The trajectory chart is the page; everything else is a footnote to it.
2. The less the better. No cards, no boxes, no shadows on content. Whitespace and one hairline
   rule separate things. If a number does not answer one of the six questions, it is not shown.
3. Color means state and nothing else. The interface is ink on paper; green, amber, orange, red
   and slate appear only as state dots, trend arrows, alert rings and signed deltas.
4. Plain words. "Heading to 68", "paying 20 days late", "drags the group". No codes, no jargon,
   no uppercase tracked labels.
5. Smooth, not showy. Curves, figures and bars ease between groups and months; nothing animates
   on load or for decoration.

## Tokens (`web/src/app.css`, `:root`)

| Role | Token | Value |
|---|---|---|
| Content surface | `--surface` | `#fdfdfc` |
| Side rail | `--side` | `#f4f4f1` |
| Row hover / selected | `--hover` / `--selected` | `#ebebe7` / `#e4e4df` |
| Hairline / strong line | `--line` / `--line-strong` | `#e3e3de` / `#c9c9c3` |
| Text: primary, secondary, muted | `--ink`, `--ink-2`, `--ink-3` | `#17181c`, `#4f525a`, `#6c6f78` |
| Comparison series | `--series-2` | `#2c5cd6` |
| State marks | `--good --warn --serious --bad --info --neutral` | see `app.css` |
| State text (deltas) | `--good-ink`, `--bad-ink` | `#146c31`, `#b32c24` |
| Easing | `--ease` | `cubic-bezier(0.16, 1, 0.3, 1)` |

State to tone mapping lives in `web/src/lib/meta.ts` (`STATE_META`). A state is always a dot plus
its word, never color alone.

## Type

One family, Geist Variable, tabular figures everywhere. Fixed scale: 12.5 (hints, sublabels),
14 (body, section headings at weight 600), 15 (list figures), 22 (offer), 30 (group name),
64 (score). Tight tracking only on the large sizes (-0.02 to -0.04em). Sentence case throughout.

## Layout

- Two panes: a 372px side rail (brand, month stepper, Groups / Alerts tabs, list) and the detail.
- Detail content is capped at 1080px: header (name left, score sentence right), chart, then two
  columns: what drives the score and companies on the left, next moves and the line on the right.
- Sections are a 14px heading with a right-aligned hint over a hairline. Rows have no borders
  except between moves.
- Below 820px the panes stack. Mobile is not a demo target.

## Components

- **List row**: name and sector, sparkline (own range, shared time axis), level, trend arrow.
  Hover and selected are background fills with an 8px radius.
- **State tag**: 7-8px dot plus label.
- **Trajectory chart** (`TrajectoryChart.tsx`): fixed 0-100 axis, dotted thresholds at 70 and 40
  labelled on the axis, 2px ink line up to the selected month and a receding grey line after it,
  a faint ink wash under a single series, alert rings in the state color, a bracket reading
  "seen N months early", crosshair tooltip, click to move the month. Comparison adds one blue
  series, a legend and end labels; the wash is dropped.
- **Pillar row**: label with its evidence in plain words, 4px ink bar, score, signed delta.
- **Controls**: borderless icon buttons for the stepper, underline tabs, one bordered select.

## Motion

`useTween` eases numeric arrays over 420ms (quartic ease-out), so lines morph and the score
counts between groups and months. CSS transitions are 180ms on backgrounds and 500ms on bars
(transform only). `prefers-reduced-motion` turns all of it off.

## Deep links

`?group=DEMO_002&compare=DEMO_001&month=2026-08-01&tab=alerts` opens the demo on a given scene.
