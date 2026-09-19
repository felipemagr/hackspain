# Design

The visual system of the X Ray demo (`web/`). Product truth lives in `PRODUCT.md`; this file
records what the built UI does so later screens follow it instead of inventing a new look.

## Principles

1. One group, one curve. The trajectory chart is the page; everything else is a footnote to it.
2. The less the better. No cards, no boxes, no shadows on content. Whitespace and one hairline
   rule separate things. If a number does not answer one of the six questions, it is not shown.
   The one filled shape is the person's own question in the chat.
3. Color means state and nothing else. The interface is Embat navy on white; three hues and a
   grey carry every state: red is trouble (falling, weak), amber is a warning (bending), green is
   good news (improving, healthy), grey is quiet (stable, bump, not enough data). They appear only
   as state dots, alert rings and signed deltas; trend arrows are grey, the shape says the direction. The palette
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
- **List row**: name, then state dot, state and sector on the second line, sparkline (own range,
  shared time axis), level, trend arrow.
  Hover and selected are background fills with an 8px radius.
- **State tag**: 7-8px dot plus label.
- **Low-data caveat** (`LowData.tsx`): under six covered months (the engine's own cut-off) the
  level is shown in `--ink-3` wherever it appears and a drawn warning glyph in ink says why. In
  the header it is a sentence, "Low confidence: 4 months of data, the score needs 6."; in a rail
  row the glyph takes the trend cell, which has nothing to draw yet, and the sentence is its
  tooltip; a company row says "4 months of data" after its name. Never a state color: it says how
  sure the score is, not how healthy.
- **Trajectory chart** (`TrajectoryChart.tsx`): 0-100 axis, dotted thresholds at 70 and 40
  labelled on the axis, 2px ink line up to the selected month and a receding grey line after it,
  a faint ink wash under a single series, alert rings in the state color, crosshair tooltip, click to move the month. Comparison adds up to four
  series, a legend and end labels; the wash is dropped. A compared group keeps its slot, and so
  its color, while others come and go. The legend entries are the remove buttons. Dragging across
  months zooms into them and the score axis closes on what is drawn (rounded to tens, thresholds
  only when inside); a line under the chart names the range, with Reset and bordered minus and
  plus buttons that zoom around the selected month. Double click resets. A click still moves the month.
- **Menu** (`Menu.tsx`): a bordered button that opens a panel of checkboxes, the multi-select
  used for Compare (with a search field, capped at four). Checked boxes are ink. The one place a shadow is allowed besides the tooltip.
- **Rail tools** (`GroupList.tsx`): one search field (words match name, sector, country or state;
  `>70` and `<40` match the score) with the favorites-only star beside it, then four quiet chips
  with counts: All, Attention, Improving, Steady. Under them a status line: "N of M groups", Clear,
  and a borderless Sort select. The default sort, Priority, keeps three sections (`BUCKETS` in
  `meta.ts`) and each heading says its own order: Needs attention, steepest fall first; Improving,
  fastest rise first; Steady, highest score first. Any other sort flattens the list.
- **Favorite star**: ink outline, filled when on, never a state color. On a row it appears on
  hover and stays once on; it also sits beside the group name. Kept in localStorage.
- **Alerts inbox** (`AlertList.tsx`): "N open" with Clear all and a clear button on row hover.
  Clearing empties the rail and its count; the rings on
  the chart stay, because they are history.
- **Pillar table** (`Pillars.tsx`): the five pillars as rows, headers in sentence case. Pillar and
  the indicator behind it on the left, then what it weighs (its base weight when coverage spreads
  it), its score, the raw indicator, and how many points it moved the level this month, signed and
  colored. Figures right-aligned, hairline between rows.
- **Own-range gauge (optional local scorecard)** (`OwnHistory.tsx`): a half dial that runs from the group's own worst month
  to its own best. A 6px arc in thirds (low, mid, high); only the third the needle sits in takes
  its state color, the rest stay hairline grey. Every scored month is a tick outside the arc,
  today's longer and in ink. Tapered ink needle, the level at 30px under the hub, the ends
  labelled with value, worst or best, and month. Below it, the zone as a dot plus its words.
- **Agents tab** (`Chat.tsx`, `FleetRail.tsx`): the rail holds the conversations and the state of
  the agent service. The detail pane holds one conversation, laid out the way a chat client does
  it: the turns growing up from the composer so the newest sits right above it, the composer at
  the bottom, and under the composer one line with a borderless "New conversation" icon button
  on the left (shown once a turn exists) and "Data as of {month}" on the right. A turn is the
  question in a filled bubble on the right
  (15px, `--hover`, 18px radius, 75% of the column at most), then the fleet's work as one
  `--side` slab with a 12px radius: a summary line (dot, "Director is reading the question" while
  it plans and then "Read as: {purpose}", the agents' names, the turn's time, a chevron) and,
  under a hairline, one row per agent (dot, name, one-line report, time) closed by the writer's
  row, which ends on its figure check ("32 figures, all traced"). The slab is open while the turn
  runs and folds to its summary line when it ends; the chevron reopens it. Then the answer as
  prose at 15px, 68ch. An agent row opens in place to its inspector: purpose, the rules it works
  under, every tool call with input, output and time, findings and sources. Tool calls are the one
  place monospace is used, because they are code. The person's bubble is the only bubble; no
  avatars, no modal. The pane follows the answer as it streams unless the reader has scrolled up.
- **Chat guide** (`Chat.tsx`): an empty conversation is centred in the pane on the composer's
  axis: a 26px title, a two-sentence lead at 15px, and a grouped list (560px, `--side`, 14px
  radius) of five rows, one per agent's ground: a 16px stroke icon on a white 28px tile, the
  topic at weight 500, one 13px line on what it answers, inset hairlines between rows. No
  suggested questions. Naming a group's id in a question sends the agents to it.
- **Conversations** (`FleetRail.tsx`): past conversations sit at the top of the Agents rail as
  alert-style rows: first question, question count, how long ago or "answering", a delete button
  on hover. "New conversation" is a text link in the section head, shown while a conversation is
  open; the button under the composer does the same. The section is sticky at the top of the rail. Kept
  in localStorage (`xray.chats.v2`). A question asked in a new conversation moves it to the top.
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

`?group=DEMO_002&month=2026-08-01&tab=alerts` (or `tab=agents`) opens the demo on a given scene.

## Internal score viewer

The local `/viewer` is an analysis workspace for provisional baseline scores. Its styles live in
`src/xray/api/static/viewer.css` and are separate from the jury demo. It uses a compact group
rail, a monthly trajectory, a five-pillar contribution table, and a quality panel. Missing values
appear as unavailable, and mixed currency and uncategorized flows remain visible beside the score.
