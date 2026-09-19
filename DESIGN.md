---
name: X Ray internal viewer
description: Restrained analysis workspace for calculated group scores
colors:
  accent: "#0b735c"
  accent-deep: "#123d36"
  text: "#202c38"
  muted: "#64727b"
  canvas: "#f7f8f8"
  rail: "#f2f5f4"
  surface: "#ffffff"
  border: "#dfe6e6"
  warning-surface: "#fff4e9"
  warning-text: "#80542b"
typography:
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "12px"
    lineHeight: 1.5
  title:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "27px"
    fontWeight: 700
    letterSpacing: "-0.035em"
rounded:
  control: "6px"
  panel: "9px"
spacing:
  compact: "10px"
  panel: "22px"
  section: "24px"
components:
  selected-group:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "11px 10px"
---

# Design System: X Ray internal viewer

## Overview

The internal viewer is an analysis desk: quiet surfaces, dense evidence, and explicit missing-data states. The score and its caveats are visible together. This is an Operate screen, not the jury-facing product demo.

## Colors

Green identifies the active group and calculated trajectory. Warm warning surfaces mark limitations in the input data. Neutral borders separate information without deep shadows.

## Typography

Use a single sans-serif family. Keep group IDs and measurements tabular. Headings are compact; labels are small but legible.

## Layout

On desktop, a searchable 292px group rail sits beside the detail view. Below 680px the rail becomes a horizontal list and the chart scrolls horizontally to retain readable monthly spacing.

## Elevation & Depth

Panels use borders and tonal separation. Only the selected group has a small soft shadow.

## Shapes

Controls use 6-7px corners; panels use 9px corners. Avoid nested cards.

## Components

The score strip holds level, trend, coverage, and observed months. A five-pillar table exposes additive contributions and month-on-month changes. The quality panel carries missingness and currency warnings.

## Do's and Don'ts

- Show unavailable values as «—», never zero.
- Keep observed data separate from `DEMO_*` data and inferred categories.
- Do not present the provisional score as a calibrated credit rating.
