---
name: Testbench
description: Laid out like SAP's cloud apps, with a petrol side rail, Libre Franklin type and the line diagram, where every suite is a line and every scenario a stop lit by its latest result.

# Source of truth: src/testbench/web/static/style.css (:root and the dark-mode block).
# Values here mirror it; change both together.
colors:
  rail: "oklch(0.29 0.05 222)"
  rail-hover: "oklch(0.34 0.055 222)"
  rail-current: "oklch(0.4 0.065 222)"
  rail-text: "oklch(0.97 0.01 222)"
  rail-text-secondary: "oklch(0.8 0.035 222)"
  canvas: "oklch(1 0 0)"
  surface-tint: "oklch(0.975 0.008 222)"
  surface-sunk: "oklch(0.967 0.009 222)"
  line: "oklch(0.91 0.01 222)"
  line-control: "oklch(0.8 0.02 222)"
  line-field: "oklch(0.6 0.03 222)"
  ink: "oklch(0.24 0.025 225)"
  ink-secondary: "oklch(0.48 0.03 225)"
  placeholder: "oklch(0.55 0.025 225)"
  petrol: "oklch(0.47 0.1 228)"
  petrol-hover: "oklch(0.41 0.095 228)"
  petrol-wash: "oklch(0.955 0.02 222)"
  track: "oklch(0.3 0.035 225)"
  positive: "oklch(0.5 0.12 150)"
  critical: "oklch(0.53 0.14 55)"
  negative: "oklch(0.52 0.19 27)"
  neutral: "oklch(0.5 0.025 225)"
  stop-passed: "oklch(0.6 0.15 150)"
  stop-failed: "oklch(0.56 0.21 27)"
  stop-error: "oklch(0.72 0.16 65)"
  stop-skipped: "oklch(0.63 0.02 225)"
typography:
  headline:
    fontFamily: "Libre Franklin, Segoe UI, system-ui, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.015em"
  title:
    fontFamily: "Libre Franklin, Segoe UI, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 700
    lineHeight: 1.3
  requirement:
    fontFamily: "Libre Franklin, Segoe UI, system-ui, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 400
    lineHeight: 1.4
  body:
    fontFamily: "Libre Franklin, Segoe UI, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Libre Franklin, Segoe UI, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 650
    lineHeight: 1.4
  mono:
    fontFamily: "Source Code Pro, ui-monospace, Consolas, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  code: "3px"
  control: "4px"
  container: "6px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "24px"
  "6": "32px"
  "7": "48px"
components:
  rail:
    backgroundColor: "{colors.rail}"
    textColor: "{colors.rail-text-secondary}"
    width: "15rem"
  rail-item-current:
    backgroundColor: "{colors.rail-current}"
    textColor: "{colors.rail-text}"
    rounded: "{rounded.control}"
  button-primary:
    backgroundColor: "{colors.petrol}"
    textColor: "{colors.canvas}"
    rounded: "{rounded.control}"
    height: "2.25rem"
    padding: "0 16px"
  button-primary-hover:
    backgroundColor: "{colors.petrol-hover}"
  button-default:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.petrol}"
    rounded: "{rounded.control}"
    height: "2.25rem"
  button-ghost:
    textColor: "{colors.petrol}"
    rounded: "{rounded.control}"
  input-text:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "2.25rem"
  line-badge:
    backgroundColor: "{colors.track}"
    textColor: "{colors.canvas}"
    rounded: "{rounded.control}"
    height: "1.75rem"
  side-region:
    backgroundColor: "{colors.surface-tint}"
    rounded: "{rounded.container}"
---

# Design System: Testbench

## Overview

**Creative North Star: "The Line."** A test suite is a route your data takes through checks, so Testbench draws it as one: a line with a stop per scenario, each stop lit by its latest result. People read a workspace the way they read a line diagram on a platform: where it is red, where it has not been yet, and what is fine.

The layout follows SAP's own cloud apps so a consultant keeps the same reflexes: a side navigation on the left (as in Datasphere and SAP Analytics Cloud), an object header with the title, description and key figures, sections with a heading and a count, one emphasized action per view, status as a shape and a word, lists with a navigation chevron, breadcrumbs on deeper pages.

The identity is Testbench's own and commits colour at page scale: a deep petrol rail, a white work area with petrol actions, Libre Franklin instead of SAP's proprietary "72", authored icons, and the line diagram. The logo is the same line with two stops lit and the last one still open.

What it deliberately is not: a grey canvas with floating white cards, soft shadows and one indigo accent. That generic AI SaaS look was tried first and dropped on 2026-10-11.

## Colors

### Rail
- **Petrol rail** (`oklch(0.29 0.05 222)`, about #05313d): the side navigation, full height, and the sign-in page ground. Its text is `oklch(0.8 0.035 222)` (7.5:1), white when current. The current item sits on `oklch(0.4 0.065 222)`.

### Work area
- **Canvas** (white): the work area. No grey ground and no cards floating on it.
- **Tint** (`oklch(0.975 0.008 222)`): regions that sit beside the main content, such as the Connections column and the business requirement.
- **Sunk** (`oklch(0.967 0.009 222)`): code, row hover.
- **Ink** (`oklch(0.24 0.025 225)`) and **secondary ink** (`oklch(0.48 0.03 225)`, 6:1 on the tint).
- **Lines**: dividers `oklch(0.91 0.01 222)`, button outlines `oklch(0.8 0.02 222)`, field borders `oklch(0.6 0.03 222)` (3.9:1).

### Action
- **Petrol** (`oklch(0.47 0.1 228)`, about #006587, 6.6:1 with white): the one primary button per view, links, focus. Hover deepens to `oklch(0.41 0.095 228)`; its wash `oklch(0.955 0.02 222)` backs hovered buttons and menu items.

### Track and stops
- **Track** (`oklch(0.3 0.035 225)`): the line itself, suite badges and table header rules.
- Stops: **passed** a green dot, **failed** a red diamond, **error** an amber square, **not tested** a grey dot, **not run yet** a hollow ring. Shape and colour, always next to the word.

### Status text
Positive green `oklch(0.5 0.12 150)`, critical amber `oklch(0.53 0.14 55)`, negative red `oklch(0.52 0.19 27)`, neutral `oklch(0.5 0.025 225)`, each at least 5:1 on white.

Dark mode follows `prefers-color-scheme` with the same roles: a darker petrol rail, a near-black petrol canvas, a light cyan-petrol action colour (`oklch(0.78 0.1 215)`) with dark text on it, and a light track.

**The Never Colour Alone Rule.** Every status is a shape or icon plus a word. Colour only reinforces.

## Typography

One family, Libre Franklin (variable, self-hosted, Latin subset, SIL OFL), a gothic with a public-signage voice, and Source Code Pro for SQL, YAML and identifiers. Steps: 0.8125, 0.875, 1, 1.125, 1.375, 1.875rem.

### Hierarchy
- **Headline** (700, 1.875rem, 1.15): page titles.
- **Title** (700, 1.125rem): section headings, workspace tiles.
- **Requirement** (400, 1.375rem, max 60ch): the business requirement on the scenario page, the most important sentence in the product.
- **Body** (400, 1rem, 1.5).
- **Label** (650, 0.875rem): field labels, buttons, statuses.
- **Mono** (400, 0.8125rem).

Numbers in tables and key figures use tabular figures.

## Layout

A 15rem petrol rail on the left, full height: brand, Workspaces, then the open workspace with its sections (Scenarios, Test runs, Connections, Settings for owners), and the account menu at the bottom. The work area holds breadcrumbs on deeper pages and a page of at most 82rem with 32px gutters.

The workspace page is an object page: a header with the title, description and four key figures (Scenarios, Failing, Last test run, Connections), separated from the content by a rule. Below it, the scenarios as lines and the test runs as a table in the main column, and the connections in a tinted 23rem column from 72rem up. Until the first test run a "Get started" route sits under the header.

On screens under 56rem the rail becomes a petrol top bar with the sections as a scrolling row, breadcrumbs collapse to a back link, the side column stacks under the main one and low-priority table columns hide.

## Elevation & Depth

Flat. Regions are separated by rules, a tint or a 1px border, never by shadow. Only menus, which float above the page, carry a shadow (`0 4px 10px`, `0 12px 32px`, petrol-tinted).

## Shapes

Small radii: 3px for code and tags, 4px for controls and the line badge, 6px for regions, tiles and menus. Circles for stops and the avatar. No nested containers.

## Components

### Line diagram (signature)
A suite is a heading set as a line badge (the suite name, white on the track colour), a short summary ("4 scenarios · 2 failing") and its actions. Under it, its scenarios hang on a 3px vertical track, each on a stop that shows its latest result, with the title, one line of requirement, the result as a word and a chevron. The track ends at the last stop. The same line, drawn horizontally, appears on workspace tiles and at the top of a report. A scenario's own page draws its checks as a route the same way, and so does "Get started".

### Rail
Items are 36px rows with an icon and a label; hover lightens the ground, the current item is filled and bold. The open workspace's name heads its group.

### Buttons
4px radius, 36px high (30px small, 44px and 40px on touch screens). **Primary** petrol with white text, at most one per view. **Default** white with an outline and petrol text (Run tests). **Ghost** without outline until hover (Test connection, Edit). **Danger** solid red, only inside a confirmation.

### Menus
`details` and `summary`, no script: Add connection, a suite's "more" menu, the account menu (which opens upwards from the rail).

### Lists and tables
Rows link to the object and show a chevron; hover uses the sunk colour. Table headers sit on a 2px track-coloured rule.

### Inputs
White, 1px field border, 4px radius, petrol border on hover and a 1px petrol ring on focus. Labels above, help below, "(optional)" in the label. Placeholders are lighter than values (4.8:1).

### Messages
A tinted strip with an icon: info on the petrol wash, errors on the red wash with the problem and how to fix it.

## Do's and Don'ts

- Do keep one primary button per view; everything else is default or ghost.
- Do draw results as stops on a line, and pair every stop with a word.
- Do put destructive actions with the object they destroy (workspace settings, the connection's or scenario's edit page), behind a disclosure, with typed confirmation for a workspace.
- Do show the business requirement before any SQL.
- Don't put white cards with soft shadows on a grey ground, or use a lone indigo or violet accent.
- Don't use SAP's "72" font, SAP icons or logos, or copy Horizon's exact tokens.
- Don't add gradient text, glassmorphism, eyebrow labels above headings or coloured side stripes on rows.
- Don't use emoji or text symbols as icons; use the authored SVG set in `src/testbench/web/icons.py` (24px grid, 1.75 stroke, round caps).
- Don't add JavaScript; menus and disclosures use `details` and `summary`.
