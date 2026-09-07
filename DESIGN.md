# DESIGN.md — OrderOrder

A design system in the [Stitch DESIGN.md](https://stitch.withgoogle.com/docs/design-md/overview/)
format, so that any agent asked to build or change this interface reads one document rather than
guessing from the code.

**This describes the system already implemented**, not an aspiration. Every token below is live in
`src/orderorder/web/static/app.css`; if the two disagree, the stylesheet is the fact and this file is
the bug. Every colour pair is asserted in `tests/test_hardening.py`, both themes.

> **This is the second design.** The first was warm bone paper, an oxblood accent and a serif, chosen
> because "law report" felt right for case law. It was, almost exactly, the palette the taste skill in
> `.claude/skills` bans by name: its list of banned premium-consumer backgrounds contains that cream
> family, its banned accents contain oxblood, and its banned text colours contain `#1a1714`, which was
> the literal hex in use. It also names serif-by-default as the single most-tested AI tell. Reaching
> for a law report because the subject is law was the reflex, not the idea. Recorded here because what
> was wrong is more useful than a clean document.

---

## 1. Visual Theme & Atmosphere

**Precise, cool, and quiet enough that colour means something.** The reference is a serious modern
instrument — a well-made piece of professional software — not a printed page and not a dashboard. Cool
neutrals, one saturated accent, a grotesque, generous negative space.

The restraint is not decoration. The product's claim is that it will not overstate: it separates
*supported*, *checked and not supported*, and *not checked*, and refuses to collapse them. So colour is
rationed. Green, amber and red appear **only** on verdicts. The interface accent is cobalt precisely so
it can never be read as a finding.

**Density:** medium. Legal text is the content and needs line length and leading; the chrome around it
should be thin.
**Mood words:** exact, calm, engineered, confident. **Never:** warm-craft, heritage,
editorial-pastiche, playful, glassy.

**Dials** (taste-skill convention): `DESIGN_VARIANCE 7 · MOTION_INTENSITY 5 · VISUAL_DENSITY 5`.

---

## 2. Colors

Three rules, in priority order.

1. **Colour means a finding.** Green, amber and red are reserved for verdicts and flags. Nothing
   decorative may borrow them, or red stops meaning *this citation is wrong*.
2. **One accent, locked.** Cobalt, everywhere, for interface only — the mark's dot, the primary button,
   focus, selection, the read-paragraph marker, links. There is no second accent anywhere.
3. **Three states, three treatments.** *Not checked* is not a milder failure and never gets a paler
   red. It is a dashed neutral — provisional rather than bad.

### Surface & ink

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#f5f6f8` | `#0a0b0d` | Page ground |
| `--surface` | `#ffffff` | `#131519` | Panels, the masthead chip |
| `--surface-2` | `#f9fafb` | `#171a1f` | Inset fields, hover, quiet fills |
| `--ink` | `#0e1116` | `#e9ecf1` | Primary text |
| `--ink-2` | `#3d444d` | `#c3c9d2` | Secondary prose, quiet button labels |
| `--muted` | `#5b636e` | `#98a0ac` | Hints, captions, status |
| `--faint` | `#69717c` | `#828a96` | Panel labels, empty states |
| `--line` | `#e6e8ec` | `#23262c` | Dividers — decorative, no contrast duty |
| `--edge` | `#858fa0` | `#5a6370` | **Control boundaries** — fields, quiet buttons |

`--line` and `--edge` look similar and are not interchangeable. A divider carries no information; the
edge that tells you a thing is a control must clear 3:1. Use `--edge` on anything you can type in or
press.

### Accent

| Token | Light | Dark | Use |
|---|---|---|---|
| `--accent` | `#2b52e0` | `#7d9bff` | The one accent |
| `--accent-press` | `#1f3fb8` | `#a3b8ff` | Hover and press |
| `--accent-ink` | `#ffffff` | `#0a0b0d` | Text **on** the accent |
| `--accent-wash` | `#eef2fe` | `#161b2c` | Selected row, read paragraph |

### Semantic — verdicts only

| Token | Light fg / bg | Dark fg / bg | Meaning |
|---|---|---|---|
| `--good` | `#0e7a4f` / `#e7f4ee` | `#3ddc97` / `#10231b` | Grades A–B; a verified quotation |
| `--warn` | `#96650a` / `#fbf1de` | `#e3b341` / `#241d10` | Grade C; quoted voice; a self-attack |
| `--bad` | `#c62f2f` / `#fdecec` | `#ff8f8a` / `#2a1618` | Grades D–F; a failure-mode chip |
| `--unchecked` | `#5b636e` / `#eef0f3` | `#98a0ac` / `#1c1f25` | **Not checked.** Always dashed |

---

## 3. Typography

### Families

| Token | Face | Used for |
|---|---|---|
| `--sans` | **Geist** 300–700, self-hosted | Everything the tool says |
| `--mono` | **Geist Mono** 400–600, self-hosted | Verbatim input and output: the brief, the plan, reports |
| `--serif` | Iowan Old Style / Palatino / Georgia | **The court's words, and only those** |

**Self-hosted, not a CDN.** The policy is `font-src 'self'`; loading Geist from Google would mean
widening it to a third-party origin, and a typeface is not worth that. Four latin/latin-ext `woff2`
subsets, 82 KB total, in `static/fonts/`, under the SIL Open Font License (`fonts/OFL.txt`). They are
served by an allowlisted route, not a directory mount.

**The serif is a voice marker, not a style.** It appears on a judgment's paragraphs, on the claim being
checked, and inside a verified quotation — the places where you are reading what somebody else wrote.
Everywhere else is Geist. This is the one justification for a serif here and it is semantic: never set
the tool's own words in it.

### Scale

| Role | Size / weight | Family |
|---|---|---|
| Wordmark | 16px / 600, `-.018em` | sans |
| Strapline, status | 13px / 400, 11.5px / 500 | sans |
| Panel label `h2` | 11px / 600, uppercase `.07em` | sans |
| Body | 15px / 1.55 | sans |
| Board row | 13.5px, citation 600 tabular | sans |
| Judgment paragraph | 15.5px / 1.7 | **serif** |
| Claim, verified quote | 16px / 15.5px | **serif** |
| Chips, tags | 11.5px / 10.5px | sans |
| Fields, `pre` | 12.75px / 12.25px | mono |

Numbers that sit under one another get `font-variant-numeric: tabular-nums` — citations, paragraph
labels, the corpus count.

---

## 4. Layout

| Region | Value |
|---|---|
| Masthead | sticky, 60px, translucent + `backdrop-filter`, 1px bottom rule |
| Page container | `max-width: 1320px`, padding `30px 28px 96px` |
| Panel | padding `20px 22px`, 1px `--line`, radius 10px, `--shadow-1` |
| Workspace row | `grid`, `minmax(0,420px) / minmax(0,1fr)`, gap 20px |
| Control cluster | `flex`, gap 9px, `margin-top: 13px` |

**The board rail is sticky above 1020px** and scrolls within `calc(100vh - 112px)`, so the list of
citations stays put while a judgment is read beside it. It goes static below that, and in print.

---

## 5. Elevation & Depth

Two shadow tokens and nothing else. `--shadow-1` on panels; `--shadow-2` only on the skip link, which
genuinely floats. Both tinted to the ink, never pure black.

Depth is otherwise carried by **surface steps** (`--bg` → `--surface` → `--surface-2`) and by 2px
left-borders in a semantic colour: `--good` on a verified quotation, `--bad` on a finding, `--warn` on
a self-attack, `--accent` on the paragraph the engine read.

---

## 6. Shapes

**SHAPE LOCK — panels `10px` · controls `6px` · badges, chips, tabs and the status pill full `999px`.**
Nothing else. Mixed radii without a rule is the fastest way to make a considered layout look assembled.

The **grade mark** is the one bespoke object: a 24px square at control radius, solid-bordered for a
decided grade and **dashed** when checks could not run.

---

## 7. Components

### Buttons
Primary is accent fill with `--accent-ink`, 13px/600. `.quiet` is `--surface` with an `--edge` border.
Press nudges 1px. Focus is a 2px accent outline at 2px offset — **never remove it.** A button that is
working is disabled, says so in its own label (`Checking…`), and takes `cursor: progress`.

### Tabs
Two variants, and the distinction is meaningful. **Surface tabs** (check / find / draft) are a
segmented pill: a capsule track with the active tab raised on `--surface`. **Panel tabs**
(`.tabs.plain`) are a quiet underline inside a card. Never mix them. The active surface is written to
`location.hash`, so a reload keeps you where you were.

### Verdict board
**A list of `<button>`s, not a table of clickable rows.** The board is a set of citations you choose
between, which is what a button is; a `<tr onclick>` is unreachable by keyboard and needs a pile of
ARIA to pretend otherwise. Each button is a two-row grid: the grade mark spans both, the citation sits
top-right, the finding chips below it. Selected takes `--accent-wash` and an accent border.

Redrawing replaces the focused element, so the handler restores focus to the row it just selected. The
first verdict opens itself as it arrives. Rows animate in with a 3px rise over 220ms — enough to notice
an arrival, not enough to be a performance.

**Chips carry the finding's words, never its number** — "no such case", "pinpoint does not exist". The
mode number goes in a `title`.

### Judgment viewer
Serif paragraphs in a scrolling column with sans tabular labels. The paragraph the engine read takes
the accent border and wash; the verified sentence inside it is `<mark>`ed in accent at 20%.

### Empty and loading states
Empty: one plain sentence in `--faint`. Loading: a **skeleton shaped like the rows it is about to
become**, never a spinner.

---

## 8. Do's and Don'ts

### Do
- Set the court's words — and only those — in the serif.
- Ration semantic colour to verdicts.
- Give *not checked* a dashed neutral.
- Keep the focus ring.
- Add a class to `app.css` rather than a `style=` attribute.
- Say what a finding is, in words.

### Don't
- **Never add inline `<script>`, `<style>`, `style=` or `on*=`.** The CSP is `script-src 'self'` with
  no `unsafe-inline`, and `tests/test_hardening.py` fails the build if any appears. This is a security
  boundary wearing a style rule's clothes.
- Never load a font, script or stylesheet from another origin — Google Fonts included.
- Never introduce a second accent, or use the accent for a verdict.
- Never use green for "done" or red for "important".
- Never render *not checked* as a lighter failure.
- No gradients beyond the loading sweep, no glassmorphism beyond the masthead's blur, no icon set, no
  emoji in the interface.
- Never interpolate server text into markup without `escape()`.

---

## 9. Responsive Behavior

| Breakpoint | Behaviour |
|---|---|
| ≥ 1021px | Two-column workspace, board rail sticky |
| ≤ 1020px | One column, rail static |
| ≤ 620px | Masthead 56px and drops the strapline; the tab row scrolls rather than wraps; panels tighten |

The page must never scroll horizontally — asserted in the render check at 1440px and 390px. Long
content scrolls inside its own container.

---

## 10. Iteration Guide

1. Read `app.css` — the header comment carries the reasoning, including what the last design got wrong.
2. Change tokens, not literals. There should be no raw hex outside `:root` and its dark override.
3. Add both themes at once. A token defined only in light is a bug.
4. Run `uv run pytest tests/test_hardening.py`: contrast in both themes, no inline script or style, no
   `on*=`, every class styled, every id the script reaches for present.
5. **Look at it.** Every visual bug in this project's history — export buttons visible when hidden, a
   tab filling on hover, a wordmark dot reading as a full stop — was invisible in the source and
   obvious on screen.

---

## 11. Known Gaps

- **No focus trap or `Escape` handling**, because there is no modal yet. The first one will need both.
- **Colour and border style alone** separate a failure chip from *needs review*. The grade mark always
  carries its letter as text; the chips do not. A glyph difference would be safer.
- **The judgment scrolls inside a fixed height**, so a long judgment is a scroll within a scroll.
  Acceptable beside a rail that must stay visible; worth revisiting.
- **No automated axe or Lighthouse pass.** The checks in `test_hardening.py` are hand-written and cover
  what was actually found wrong, which is not the same as coverage.
- **`backdrop-filter` has no fallback.** Where unsupported the masthead is simply 82% opaque, which is
  fine, but it has not been looked at on an old browser.
