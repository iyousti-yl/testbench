---
name: Testbench
description: Calm, precise operating surfaces that sit naturally next to SAP's cloud apps, with an indigo brand and a health strip that shows every scenario's latest result.

# Source of truth: src/testbench/web/static/style.css (:root and the dark-mode block).
# Values here mirror it; change both together.
colors:
  canvas: "oklch(0.972 0.004 250)"
  surface: "oklch(1 0 0)"
  surface-sunk: "oklch(0.955 0.006 250)"
  line: "oklch(0.905 0.008 250)"
  line-control: "oklch(0.82 0.015 250)"
  line-field: "oklch(0.62 0.03 250)"
  ink: "oklch(0.24 0.03 250)"
  ink-secondary: "oklch(0.47 0.035 250)"
  placeholder: "oklch(0.56 0.03 250)"
  indigo: "oklch(0.5 0.19 266)"
  indigo-hover: "oklch(0.44 0.18 266)"
  indigo-wash: "oklch(0.955 0.025 266)"
  focus: "oklch(0.42 0.19 266)"
  positive: "oklch(0.5 0.12 150)"
  positive-wash: "oklch(0.965 0.035 150)"
  critical: "oklch(0.53 0.14 55)"
  critical-wash: "oklch(0.97 0.04 80)"
  negative: "oklch(0.5 0.18 25)"
  negative-wash: "oklch(0.965 0.025 20)"
  neutral: "oklch(0.5 0.03 250)"
  segment-passed: "oklch(0.63 0.14 150)"
  segment-failed: "oklch(0.57 0.2 25)"
  segment-error: "oklch(0.74 0.15 65)"
  segment-skipped: "oklch(0.8 0.015 250)"
typography:
  headline:
    fontFamily: "Source Sans 3, Segoe UI, system-ui, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Source Sans 3, Segoe UI, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 650
    lineHeight: 1.3
  requirement:
    fontFamily: "Source Sans 3, Segoe UI, system-ui, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 400
    lineHeight: 1.4
  body:
    fontFamily: "Source Sans 3, Segoe UI, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Source Sans 3, Segoe UI, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 600
    lineHeight: 1.4
  mono:
    fontFamily: "Source Code Pro, ui-monospace, Consolas, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.55
rounded:
  code: "4px"
  control: "8px"
  container: "12px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "24px"
  "6": "32px"
  "7": "48px"
components:
  button-primary:
    backgroundColor: "{colors.indigo}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    height: "2.25rem"
    padding: "0 16px"
  button-primary-hover:
    backgroundColor: "{colors.indigo-hover}"
  button-default:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.indigo}"
    rounded: "{rounded.control}"
    height: "2.25rem"
  button-ghost:
    textColor: "{colors.indigo}"
    rounded: "{rounded.control}"
  input-text:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "2.25rem"
    padding: "6px 11px"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.container}"
    padding: "16px 24px"
  shell-bar:
    backgroundColor: "{colors.surface}"
    height: "3rem"
---

# Design System: Testbench

## Overview

**Creative North Star: "The Inspection Bench."** A clean, well-lit work surface where every object is laid out, labelled and checked. Testbench is operated, not browsed: people come to write a scenario, run it, and read what broke.

The structure is deliberately compatible with SAP's current cloud look (Fiori Horizon, SAP Analytics Cloud, Datasphere), so a consultant switching between them keeps the same reflexes: a white shell bar with breadcrumbs and an avatar menu, a light cool canvas, white panels with soft shadows, 36px controls, one emphasized blue action per view, object status as icon plus text, lists with a navigation chevron, toolbars with a count in brackets, launchpad-style tiles on the home page.

The identity is Testbench's own: Source Sans 3 instead of SAP's proprietary "72", an indigo brand instead of SAP blue, authored outline icons, and the **health strip**: one small segment per scenario, coloured by its latest result. It appears on workspace tiles, suite toolbars and the report, and the logo mark is built from the same bars.

## Colors

### Primary
- **Bench Indigo** (`oklch(0.5 0.19 266)`, about #3056cd): the one emphasized action per view, links, focus, the logo ground. Hover deepens to `oklch(0.44 0.18 266)`. Its wash (`oklch(0.955 0.025 266)`) backs hovered menu items and info messages.

### Status
- **Positive green** (`oklch(0.5 0.12 150)`): passed, connected.
- **Critical amber** (`oklch(0.53 0.14 55)`): errors (a check could not run), changed objects.
- **Negative red** (`oklch(0.5 0.18 25)`): failed, cannot connect, destructive actions.
- **Neutral slate** (`oklch(0.5 0.03 250)`): not tested.
- Strip segments use brighter versions of the same hues; "not run yet" is a hollow segment.

### Neutral
- **Canvas** (`oklch(0.972 0.004 250)`): page ground.
- **Surface** (white): shell bar, panels, inputs.
- **Sunk** (`oklch(0.955 0.006 250)`): code blocks, row hover.
- **Ink** (`oklch(0.24 0.03 250)`) and **secondary ink** (`oklch(0.47 0.035 250)`, 6.8:1 on white): text and supporting text.
- **Lines**: dividers `oklch(0.905 0.008 250)`, button outlines `oklch(0.82 0.015 250)`, field borders `oklch(0.62 0.03 250)` (3.6:1, visible as a control edge).

Dark mode follows `prefers-color-scheme` with the same roles: a cool near-black canvas, raised surfaces with a 1px border instead of a shadow, a lighter indigo (`oklch(0.74 0.13 266)`) with dark text on it.

**The Never Colour Alone Rule.** Every status is an icon plus a word. Colour only reinforces.

## Typography

One family, Source Sans 3 (variable, self-hosted, SIL OFL), with Source Code Pro for SQL, YAML and identifiers. The scale is fixed rem steps with a ratio near 1.2: 0.8125, 0.875, 1, 1.125, 1.375, 1.75rem.

### Hierarchy
- **Headline** (700, 1.75rem, 1.2): page titles.
- **Title** (650, 1.125rem, 1.3): panel and section headings, workspace tiles.
- **Requirement** (400, 1.375rem, 1.4, max 60ch): the business requirement on the scenario page, the most important sentence in the product.
- **Body** (400, 1rem, 1.5): text and inputs.
- **Label** (600, 0.875rem): field labels, buttons, statuses, table headers.
- **Mono** (400, 0.8125rem): queries, check definitions, ids.

Numbers in tables use tabular figures.

## Layout

A centred page of at most 80rem with 24px gutters (16px on phones). Forms use a narrower 46rem or 60rem column. The workspace page is an object page: header with title, description and Settings; a "Get started" checklist until the first test run; then a main column (scenarios grouped per suite, recent runs) and a 23rem side column (connections) from 68rem up. Spacing follows a 4px base: 4, 8, 12, 16, 24, 32, 48px. On phones the breadcrumbs collapse to a back link to the parent, side columns stack under the main column, and low-priority table columns hide.

## Elevation & Depth

Light, ambient elevation, as in SAP Horizon: surfaces sit just above the canvas.

### Shadow Vocabulary
- **Panel** (`0 1px 2px oklch(0.3 0.03 250 / 0.1), 0 2px 6px oklch(0.3 0.03 250 / 0.06)`): panels and tiles at rest.
- **Raised** (`0 4px 10px oklch(0.3 0.03 250 / 0.1), 0 12px 32px oklch(0.3 0.03 250 / 0.14)`): menus and hovered tiles.
- **Shell** (`0 1px 0 line, 0 2px 6px oklch(0.3 0.03 250 / 0.06)`): the sticky shell bar.

In dark mode panels drop the shadow and take a 1px border.

## Shapes

Three radii: 4px for code chips and tags, 8px for controls (buttons, inputs, menu items, messages), 12px for containers (panels, tiles, menus). Circles only for the avatar and step markers. No nested cards: a panel contains rows, toolbars and dividers, never another panel.

## Components

### Buttons
- **Shape:** 8px radius, 36px high (30px small; 44px and 40px on touch screens).
- **Primary:** indigo with white text. At most one per view: New workspace, New scenario, Run this scenario, Save, Sign in.
- **Default:** white with an outline and indigo text, for secondary actions such as Run tests on a suite.
- **Ghost:** no outline until hover, for in-row actions (Test connection, Map lineage, Edit, Settings).
- **Danger:** solid red, only inside a confirmation (typed for workspaces).
- **States:** hover washes or deepens, 1px press, 2px focus ring offset 2px, disabled at 45% opacity.

### Menus
`details` and `summary` (no script): Add connection, the suite's "more" menu, the avatar menu. Items have an icon, a label and an optional one-line explanation.

### Panels and toolbars
White, 12px radius, panel shadow. A toolbar row carries the heading with its count in brackets, and actions on the right.

### Lists
Rows with a status icon, a title, one line of supporting text and a chevron, linking to the object. Hover uses the sunk colour.

### Inputs
White, 1px field border, 8px radius. Hover turns the border indigo; focus adds a 1px indigo ring. Labels above, help below in secondary ink, "(optional)" in the label. Placeholders are lighter than values (4.6:1).

### Messages
A strip with an icon, a tinted background and a hairline border: info in indigo wash, errors in red wash with the problem and how to fix it.

### Health strip (signature)
A row of thin segments (6px high, 2px gaps), one per scenario, coloured by its latest test run result: green passed, red failed, amber error, slate not tested, hollow not run yet. Always followed by a short text such as "2 failing" or "all passing".

### Onboarding steps
Numbered steps (Connect a system, Write a test scenario, Run the tests) with the current step in indigo and done steps checked in green. The panel disappears after the first test run.

## Do's and Don'ts

- Do keep one primary button per view; everything else is default or ghost.
- Do put destructive actions with the object they destroy (workspace settings, the connection's or scenario's edit page), behind a disclosure, with typed confirmation for a workspace.
- Do show the business requirement before any SQL.
- Do pair every status colour with an icon and a word.
- Don't use SAP's "72" font, SAP icons or logos, or copy Horizon's exact tokens.
- Don't nest panels, add coloured side stripes, gradient text or eyebrow labels above headings.
- Don't use emoji or text symbols as icons; use the authored SVG set in `src/testbench/web/icons.py` (24px grid, 1.75 stroke, round caps).
- Don't add JavaScript; menus and disclosures use `details` and `summary`.
