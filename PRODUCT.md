# Product

<!-- impeccable:product-schema 1 -->

## Platform

web (server-rendered, no JavaScript), plus a command line for CI.

## Users

SAP analytics and integration consultants, and the client teams they work with, who own data flows in SAP Datasphere, SAP SuccessFactors and the systems around them. They know their data models well and live in SAP's cloud tools all day (Fiori launchpad, SAP Analytics Cloud, Datasphere). They open Testbench between changes and transports: to write a scenario from a business requirement, run it, and see what broke.

## Product Purpose

Testbench keeps business scenarios tested after every change. A scenario keeps the requirement in plain words next to the checks that prove it, runs against real records, and shows a clear result and diff. Success is measured by defects caught before go-live that the usual unit tests miss: data anomalies and logic that does not handle realistic cases.

## Positioning

A connector-agnostic regression testing tool for SAP data landscapes, lighter and faster to adopt than migration-focused test suites. Datasphere and SuccessFactors are the first connectors; the core never depends on one system.

## Operating Context

Users sign in, open a workspace per client or project, connect systems with read-only users, write scenarios (in the app, or with the `write-scenario` skill in Claude Code), capture baselines and run suites. Results are read in the app or as a self-contained HTML report. A workspace is only visible to its members.

## Capabilities and Constraints

- Workspaces, connections (SAP Datasphere, SAP SuccessFactors), scenarios and suites, runs and reports, baselines, lineage with change detection.
- Synthetic data only in the repository and in demos. No real client data, hostnames, credentials or tenant names.
- Personal data stays out of baselines (hash mode) and lineage holds metadata only.
- No JavaScript in the app: strict Content-Security-Policy, forms and `details` elements only.

## Brand Commitments

Precise, calm, trustworthy. Testbench should feel at home next to SAP's own cloud applications, so a consultant does not switch mental models when moving between them, while being clearly its own product. It is a tool people operate, not a marketing site: familiar controls, quiet surfaces, one clear action per view, and status that is readable at a glance.

Three-word personality: **precise, calm, dependable**.

Avoid:

- Copying SAP's proprietary assets (the "72" font, SAP icons, logos, exact theme tokens). Compatible structure, own identity.
- Dashboard clichés: big hero numbers, gradient charts, decorative sparklines.
- Colour alone for meaning. Every status carries an icon and a word.

## Product Principles

1. **Less is more, but nothing missing.** Show what the person needs for the next step; keep the rest one click away.
2. **The requirement leads.** Every scenario and every result shows the business sentence first, the SQL second.
3. **One place for each thing.** Create, edit and delete an object where it lives: settings hold rename and delete, a connection's page holds its delete.
4. **Safe by default.** Read-only users, encrypted secrets, members-only workspaces, typed confirmation for destructive actions.

## Accessibility & Inclusion

WCAG 2.1 AA: contrast checked with real ratios (body text and placeholders at least 4.5:1), visible focus rings, keyboard reachable menus (`details`/`summary`), status as icon plus text, respect for `prefers-reduced-motion` and `prefers-color-scheme`, touch targets of 44px on coarse pointers.
