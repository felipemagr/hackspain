# Design

The visual system of the X Ray demo (`web/`). Product truth lives in `PRODUCT.md`; this file
records what the built UI does so later screens follow it instead of inventing a new look.

## Principles

1. One group, one curve. The trajectory chart is the page; everything else is a footnote to it.
2. The less the better. No cards, no boxes, no shadows on content. Whitespace and one hairline
   rule separate things. If a number does not answer one of the six questions, it is not shown.
3. Color means state and nothing else. The interface is Embat navy on white; green, amber, orange,
   red and blue appear only as state dots, trend arrows, alert rings and signed deltas. The palette
   is Embat's (embat.io design tokens); the brand gradient lives only in the logo mark.
4. Plain words. "Heading to 68", "paying 20 days late", "drags the group". No codes, no jargon,
   no uppercase tracked labels.
5. Smooth, not showy. Curves, figures and bars ease between groups and months; nothing animates
   on load or for decoration.

## Tokens (`web/src/app.css`, `:root`)

| Role | Token | Value |
|---|---|---|
| Content surface | `--surface` | `#ffffff` |
| Side rail | `--side` | `#f3f4f6` |
| Row hover / selected | `--hover` / `--selected` | `#e8e8ed` / `#dddde6` |
| Hairline / strong line | `--line` / `--line-strong` | `#e8e8ed` / `#d2d2db` |
| Text: primary, secondary, muted | `--ink`, `--ink-2`, `--ink-3` | `#050b2c`, `#42444c`, `#6e707c` |
| Comparison series, by slot | `--series-2` to `--series-5` | `#8041d1`, `#00a39b`, `#b0661a`, `#d0408f` |
| State marks | `--good --warn --serious --bad --info --neutral` | see `app.css` |
| State text (deltas) | `--good-ink`, `--bad-ink` | `#007d25`, `#ab2807` |
| Easing | `--ease` | `cubic-bezier(0.16, 1, 0.3, 1)` |

State to tone mapping lives in `web/src/lib/meta.ts` (`STATE_META`). A state is always a dot plus
its word, never color alone.

## Type

One family, Geist Variable, tabular figures everywhere. Fixed scale: 12.5 (hints, sublabels),
14 (body, section headings at weight 600), 15 (list figures), 22 (offer), 30 (group name),
64 (score). Tight tracking only on the large sizes (-0.02 to -0.04em). Sentence case throughout.

## Layout

- Two panes: a 372px side rail (brand, Groups / Alerts tabs, list) and the detail.
- Detail content is capped at 1080px: header (name left, score sentence right), chart, then two
  columns: what drives the score and companies on the left, next moves and the line on the right.
- Sections are a 14px heading with a right-aligned hint over a hairline. Rows have no borders
  except between moves.
- Below 820px the panes stack. Mobile is not a demo target.

## Components

- **Lockup** (`App.tsx`): the rail header is `docs/brand/lockup-embat-lighthouse.svg` in markup:
  the Lighthouse mark below, Embat's wordmark in ink, a 22px hairline, then "Lighthouse" in the
  brand type. The same lockup in white closes the brand video (`docs/brand/video/`).
- **Brand mark** (`public/favicon.svg`): three ink facets in the angular language of
  Embat's isotype, opened to show a facet inside in Embat's blue to purple gradient: the lit
  lantern of the lighthouse. The favicon is the same mark with no tile: ink facets, white in a dark browser. Sources and rejected
  options in `docs/brand/`.
- **List row**: name and sector, sparkline (own range, shared time axis), level, trend arrow.
  Hover and selected are background fills with an 8px radius.
- **State tag**: 7-8px dot plus label.
- **Low-data caveat** (`LowData.tsx`): under six covered months (the engine's own cut-off) the
  level is shown in `--ink-3` wherever it appears and a drawn warning glyph in ink says why. In
  the header it is a sentence, "Low confidence: 4 months of data, the score needs 6."; in a rail
  row the glyph takes the trend cell, which has nothing to draw yet, and the sentence is its
  tooltip; a company row says "4 months of data" after its name. Never a state color: it says how
  sure the score is, not how healthy.
- **Trajectory chart** (`TrajectoryChart.tsx`): fixed 0-100 axis, dotted thresholds at 70 and 40
  labelled on the axis, 2px ink line up to the selected month and a receding grey line after it,
  a faint ink wash under a single series, alert rings in the state color, crosshair tooltip, click to move the month. Comparison adds up to four
  series, a legend and end labels; the wash is dropped. A compared group keeps its slot, and so
  its color, while others come and go. The legend entries are the remove buttons.
- **Menu** (`Menu.tsx`): a bordered button that opens a panel of checkboxes, the multi-select
  used for Compare (with a search field, capped at four) and for the rail's Filter (state and
  trend). Checked boxes are ink. The one place a shadow is allowed besides the tooltip.
- **Rail tools** (`GroupList.tsx`): Filter menu, a sort select (by state keeps the buckets; any
  other sort flattens the list and moves the state onto the row's second line) and a Favorites
  toggle. Any active filter shows "N of M groups" and a Clear filters link.
- **Favorite star**: ink outline, filled when on, never a state color. On a row it appears on
  hover and stays once on; it also sits beside the group name. Kept in localStorage.
- **Alerts inbox** (`AlertList.tsx`): "N open" with Clear all and a clear button on row hover.
  Clearing empties the rail and its count; the rings on
  the chart stay, because they are history.
- **Pillar table** (`Pillars.tsx`): the five pillars as rows, headers in sentence case. Pillar and
  the indicator behind it on the left, then what it weighs (its base weight when coverage spreads
  it), its score, the raw indicator, and how many points it moved the level this month, signed and
  colored. Figures right-aligned, hairline between rows.
- **Own-range gauge** (`OwnHistory.tsx`): a half dial that runs from the group's own worst month
  to its own best. A 6px arc in thirds (low, mid, high); only the third the needle sits in takes
  its state color, the rest stay hairline grey. Every scored month is a tick outside the arc,
  today's longer and in ink. Tapered ink needle, the level at 30px under the hub, the ends
  labelled with value, worst or best, and month. Below it, the zone as a dot plus its words.
- **Agents tab** (`Chat.tsx`, `FleetRail.tsx`): the rail lists the director (planner), the agents
  and the writer, each with its live state and the tool it is running. The detail pane holds the
  conversation. A turn is the question at 22px, a line saying what the planner read it as, a
  trace of the agents dispatched (dot, name, one-line report, time) closed by the writer's own
  row, which ends on its figure check ("32 figures, all traced"), then the answer as prose at
  15px, 68ch. A trace row opens in place to the agent's inspector: purpose, the rules it works
  under, every tool call with input, output and time, findings and sources. Tool calls are the
  one place monospace is used, because they are code. No bubbles, no avatars, no modal.
- **Chat guide** (`Chat.tsx`): an empty conversation shows no suggested questions. It shows a
  short lead and a five-row guide, topic at weight 500 and one plain line on what it answers,
  one row per agent's ground. The group is changed with the "Ask about" select in the chat
  header; naming another group's id in a question compares it.
- **Conversations** (`FleetRail.tsx`): past conversations sit at the top of the Agents rail, above
  the fleet, as alert-style rows: first question, group and question count, how long ago, a delete
  button on hover. "New conversation" is a text link in the section head. The section is sticky at
  the top of the rail; the list is three rows tall and scrolls for the rest. Kept in localStorage (`xray.chats`, last 30); opening one selects its group.
- **Data sync** (`GroupDetail.tsx`): a borderless refresh icon beside the favorite star, same size
  and ink. It turns while the tables refetch, and only then. The meta line ends with when the data
  was last updated (the tables' Last-Modified); the icon's tooltip says when this browser synced.
- **Draft suggestion**: between two strong hairlines under the answer, with the only filled
  button on the tab, "Sign". Anything that moves money is a draft until a person signs it.
- **Agent dot**: hollow at rest, blue and pulsing while working, ink once it reported, red when
  it failed. The only motion on the tab besides the streaming caret.
- **Controls**: borderless icon buttons, underline tabs, bordered selects and
  menu buttons, underlined text links for secondary actions (Clear all, Clear filters).

## Motion

`useTween` eases numeric arrays over 420ms (quartic ease-out), so lines morph and the score
counts between groups and months. CSS transitions are 180ms on backgrounds and 500ms on bars
(transform only). `prefers-reduced-motion` turns all of it off.

## Deep links

`?group=DEMO_002&compare=DEMO_001,DEMO_003&month=2026-08-01&tab=alerts` (or `tab=agents`) opens the demo on a given scene.

## Internal score viewer

The local `/viewer` is an analysis workspace for provisional baseline scores. Its styles live in
`src/xray/api/static/viewer.css` and are separate from the jury demo. It uses a compact group
rail, a monthly trajectory, a five-pillar contribution table, and a quality panel. Missing values
appear as unavailable, and mixed currency and uncategorized flows remain visible beside the score.
