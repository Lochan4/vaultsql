# VaultSQL Frontend — Design Principles

## What VaultSQL Is

A self-hosted text-to-SQL tool for small companies. Users connect a database,
ask questions in plain English, and get SQL + results + charts. The interface
must feel like a **precision tool** — purposeful, fast, distraction-free.
Not a marketing page. Not a dashboard product. A focused workspace.

---

## Core Philosophy

**Utility first. Clarity always. No decoration for decoration's sake.**

Every design decision should serve the user's primary job: ask a question,
read the result, decide what to ask next. Anything that doesn't support
that loop doesn't belong in the interface.

- Clarity over cleverness
- Data is the hero — the UI is the frame
- Density without clutter — analysts want to see more, not less
- Light, calm, and warm — like a clean notepad
- Zero onboarding friction — one step to connect, one step to query

---

## Color System

All colors are defined as CSS custom properties in `src/styles/tokens.css`.
**Never use hardcoded hex values in components.** Always use tokens.

### Core anchors (the two defining colors)

```
Background: #FFFFF0   — ivory, warm and light
Foreground: #71797E   — steel gray, neutral and readable
```

### Full token set

```css
/* Backgrounds */
--bg:          #FFFFF0   /* page background — ivory */
--bg-surface:  #F5F5E6   /* cards, sidebar, panels */
--bg-elevated: #EBEBD8   /* hover states, dropdowns, active items */
--bg-input:    #F0F0E3   /* input fields, code blocks */

/* Text */
--fg:          #71797E   /* primary text — steel gray */
--fg-strong:   #4A5055   /* headings, emphasis */
--fg-muted:    #A0A8AD   /* secondary text, placeholders, timestamps */
--fg-subtle:   #C5CBCE   /* dividers, disabled text */

/* Accent */
--accent:      #A07850   /* warm caramel brown — CTAs, links, active states */
--accent-dim:  rgba(160, 120, 80, 0.12)   /* accent backgrounds */
--accent-fg:   #FFFFF0   /* text on accent backgrounds */

/* Semantic */
--success:     #4A8C5C   /* good query, verified — muted green */
--error:       #B85450   /* bad query, errors — muted red */
--warning:     #9C7B3A   /* caution — muted amber */

/* Borders */
--border:      rgba(113, 121, 126, 0.14)  /* default border */
--border-mid:  rgba(113, 121, 126, 0.26)  /* stronger border */
--border-strong: rgba(113, 121, 126, 0.40) /* focus rings, active */
```

### Rules
- The two anchor colors (`#FFFFF0` and `#71797E`) must always be correct — never deviate
- NO pure white (#FFFFFF) — use `--bg` (#FFFFF0) instead
- NO pure black — use `--fg-strong` (#4A5055) for the darkest text
- NO gradients — flat color only
- NO drop shadows — use `--border` or `--border-mid` for elevation
- NO third accent colors — warm brown + semantic colors only
- NO blue anywhere in the UI

---

## Typography

**Two typefaces only:**

| Use | Font | Stack |
|-----|------|-------|
| UI / prose | Space Grotesk | `'Space Grotesk', system-ui, sans-serif` |
| SQL / code / data | JetBrains Mono | `'JetBrains Mono', 'Fira Code', monospace` |

### Scale
```
--text-xs:   11px / 1.4  — labels, timestamps, metadata
--text-sm:   13px / 1.5  — secondary text, table cells
--text-base: 14px / 1.6  — body, chat messages
--text-md:   16px / 1.5  — section headings
--text-lg:   20px / 1.3  — page titles
```

### Rules
- Body text: Space Grotesk 14px weight 400, color `--fg`
- Headings: Space Grotesk weight 600, color `--fg-strong`
- SQL blocks: JetBrains Mono 13px weight 400
- Result table cells: JetBrains Mono 13px — numbers are data, treat them as code
- Labels / metadata: Space Grotesk 11px weight 500, letter-spacing 0.04em, color `--fg-muted`
- NO font sizes below 11px
- NO font weights above 600 in body copy

---

## Layout

### Page structure
```
┌─────────────────────────────────────────────┐
│  Sidebar (240px fixed)  │  Main area (flex)  │
│  ─────────────────────  │  ─────────────────  │
│  DB selector            │  TopBar (48px)      │
│  Chat list              │  ─────────────────  │
│  ─────────────────────  │  Chat thread        │
│  [New Chat]             │  (scrollable)       │
│                         │  ─────────────────  │
│                         │  Input bar (72px)   │
└─────────────────────────────────────────────┘
```

- Sidebar: `240px` fixed, `--bg-surface` background, `--border` right border
- TopBar: `48px`, shows active DB + model used
- Input bar: `72px`, sticks to bottom
- Chat thread: fills remaining height, scrolls independently

### Spacing
```
--space-1:  4px
--space-2:  8px
--space-3:  12px
--space-4:  16px
--space-6:  24px
--space-8:  32px
--space-12: 48px
```

### Border radius
```
--radius-sm: 4px   — inputs, tags, badges
--radius-md: 6px   — cards, bubbles, buttons
--radius-lg: 8px   — modals, dropdowns
```
NO pill shapes (no `9999px`) except single-character status badges.

---

## Component Patterns

### Chat messages

**User bubble:**
- Background: `--accent-dim`
- Border: 1px solid `rgba(160, 120, 80, 0.25)`
- Align: right
- Font: Space Grotesk 14px, color `--fg`

**Assistant bubble:**
- Background: `--bg-surface`
- Border: 1px solid `--border`
- Align: left
- Sequence inside: explanation → SQL block → result table → chart

### SQL blocks
- Background: `--bg-input`
- Border: 1px solid `--border-mid`
- Font: JetBrains Mono 13px, color `--fg`
- Padding: 12px 16px
- Header row: "SQL" label left (`--fg-muted`, 11px), copy button right
- Syntax highlighting: keywords in `--accent`, strings in `--success`, comments in `--fg-subtle`

### Result tables
- Full width within bubble
- Font: JetBrains Mono 13px for cells, Space Grotesk 11px weight 500 for headers
- Header: uppercase, `--fg-muted`, `--border-mid` bottom border
- Row hover: `--bg-elevated`
- Numeric columns: right-aligned
- Max 50 rows; "Show all N rows" expander below if truncated
- Border: 1px solid `--border` around entire table

### Charts
- Rendered as base64 PNG by the backend — display as `<img>`
- Container background: `--bg-input`
- Border: 1px solid `--border-mid`
- Max width: 100% of bubble
- NO chart recreation in JS — trust the backend rendering

### Input bar
- Background: `--bg-surface`, top border: 1px solid `--border`
- Single `<textarea>`, grows with content (max 5 lines), no resize handle
- Font: Space Grotesk 14px, color `--fg`
- Send on Enter, newline on Shift+Enter
- Placeholder: "Ask anything about your data…" color `--fg-muted`
- Send button: `--accent` fill, `--accent-fg` icon, `--radius-md`

### DB Connector (onboarding)
- Full-screen, centered card — `--bg-surface`, `--border-mid` border, `--radius-lg`
- DB type selector: pill tabs (PostgreSQL / MySQL / SQLite / MSSQL)
- Connection form: labeled inputs, `--bg-input` fill
- "Test connection" button before save — shows `--success` or `--error` inline
- NO modal — it is the full page

### Sidebar items (chat list)
- Default: transparent background, `--fg-muted` text
- Hover: `--bg-elevated`
- Active: `--accent-dim` background, 2px left border `--accent` (brown), `--fg-strong` text
- Timestamp: `--fg-subtle`, 11px, right-aligned

---

## Motion

Minimal. Functional only.

```
--duration-fast:   100ms  — hover, button press
--duration-base:   200ms  — panel open, dropdown
--duration-slow:   300ms  — page transition
--ease-standard:   cubic-bezier(0.4, 0, 0.2, 1)
```

- Chat messages: `opacity 0→1` + `translateY 6px→0`, 200ms ease-standard
- Loading: pulsing `--fg-subtle` skeleton lines — not spinners
- No bounce. No spring. No decorative animation.

---

## States

Every interactive element must have all states styled:

| State | Treatment |
|-------|-----------|
| Default | base token values |
| Hover | `--bg-elevated` background |
| Active/pressed | 100ms, slightly darker |
| Disabled | `--fg-subtle` color, 60% opacity, `cursor: not-allowed` |
| Focus | 2px `--accent` outline, 2px offset — NEVER remove the focus ring |

---

## Loading & Error States

**Query loading (step indicator):**
- Input disabled while processing
- In assistant area: `Extracting anchors… → Finding joins… → Generating SQL… → Running query`
- Each step: small dot pulse animation, `--fg-muted` text, 13px

**Error bubble:**
- Background: `rgba(184, 84, 80, 0.08)` — `--error` at low opacity
- Border: 1px solid `rgba(184, 84, 80, 0.30)`
- Error message in `--error` color, readable
- "Try rephrasing" suggestion below in `--fg-muted`

**Empty state:**
- Centered in main area
- Headline: "Ask anything about your data" — Space Grotesk 20px, `--fg-strong`
- 3 clickable example question chips — `--bg-elevated` fill, `--border-mid` border

---

## What NOT to Do

- NO pure white (#FFFFFF) — always use `--bg` (#FFFFF0)
- NO pure black — use `--fg-strong` at most
- NO gradients
- NO glassmorphism
- NO drop shadows
- NO spinners — skeleton states only
- NO icon-only buttons without accessible `aria-label`
- NO placeholder as the only label — always a visible label above inputs
- NO hardcoded colors in component files — CSS tokens only
- NO dark backgrounds except `--bg-input` for code/SQL blocks
