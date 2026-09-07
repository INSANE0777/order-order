# DESIGN.md — OrderOrder

A design system in the [Stitch DESIGN.md](https://stitch.withgoogle.com/docs/design-md/overview/)
format, so that any agent asked to build or change this interface reads one document rather than
guessing from the code.

**This describes the system already implemented**, not an aspiration. Every token below is live in
`src/orderorder/web/static/app.css`; if the two disagree, the stylesheet is the fact and this file is
the bug. Every colour pair is asserted in `tests/test_hardening.py`, both themes.

> **This is the third design, and it was built to a reference.** The first was warm paper, oxblood and
> a serif — the palette the taste skill bans by hex, and serif-by-default, the AI tell it names. The
> second was cool greys, one cobalt and Geist — competent, and indistinguishable from every tool built
> that year. The reference that fixed it was an animation studio's site: a stone architectural stage,
> a recessed frame holding a circular object lit in one cool colour, tiny wide-set navigation, and an
> editorial index strip in hairline rows. That language maps onto this product almost without
> translation, because **a court seal is a circle in a square**. The lesson kept: a good UI has one
> idea. The first two had a mood.

---

## 1. Visual Theme & Atmosphere

**A stone stage, a frame, a seal, an index.** The interface is architectural: concrete slabs with
bevelled seams and a grain, one slab recessed to hold a sheet of paper, a circular seal stamped on the
recess's lower edge, and beneath it a strip of hairline rows like a studio's client index. The one
lit object on the page is the seal.

Each element is the product, not decoration:

| element | what it is | why it looks like that |
|---|---|---|
| **the frame** | the recessed slab | it *holds a document* — the brief, in a paper slot |
| **the seal** | the aqua circle | the one action that matters; its ring fills as citations resolve |
| **the index** | hairline rows below | the verdicts: three columns, tiny labels, nothing decorative |
| **the document** | the paper pane | the judgment, in a serif, because it is the court's voice |

**Density:** medium; the stage is airy, the index and document are dense.
**Mood words:** architectural, material, exact, lit. **Never:** flat SaaS, warm-craft, glassy, playful.

**Dials** (taste-skill convention): `DESIGN_VARIANCE 8 · MOTION_INTENSITY 6 · VISUAL_DENSITY 5`.

---

## 2. Colors

Three rules, in priority order.

1. **Colour means a finding.** Green, amber and red are reserved for verdicts and flags. Nothing
   decorative may borrow them, or red stops meaning *this citation is wrong*.
2. **The aqua is a lit object, never text.** It measures **1.19:1** against the stone. It appears on the
   seal, the brand mark, the selected-row bar, and the wash behind a read paragraph — always as a fill
   with dark ink on it, or as a glow. Where the accent must carry text or a focus ring, it is the deep
   teal `--accent`, which does pass.
3. **Three states, three treatments.** *Not checked* is not a milder failure and never gets a paler
   red. It is a dashed neutral — provisional rather than bad.

### Stone & paper

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#cbc5bb` | `#1c1d1f` | The stone: page ground, index |
| `--surface` | `#f4f3f0` | `#26282b` | Paper: the slot, the document pane, the status pill |
| `--surface-2` | `#bdb6ab` | `#151617` | The recessed frame's interior |
| `--ink` | `#17181a` | `#ecebe7` | Primary text |
| `--ink-2` | `#3a3a37` | `#c8c6c0` | Navigation, secondary prose |
| `--muted` | `#494944` | `#a09e97` | Hints, captions |
| `--faint` | `#494843` | `#908e87` | Slot and paragraph labels |
| `--line` | `rgba(23,24,26,.14)` | `rgba(236,235,231,.10)` | Hairlines — decorative, no contrast duty |
| `--edge` | `#66625c` | `#6e7178` | **Control boundaries** — measured 3.01 on the stone |
| `--hi` / `--lo` | `rgba(255,255,255,.42)` / `rgba(0,0,0,.16)` | `.07` / `.55` | The bevel: one light seam, one dark |

### The seal, and the accent

| Token | Light | Dark | Use |
|---|---|---|---|
| `--seal` | `#3ec6d6` | `#5fd4e2` | The lit object. **Never text, never an edge.** |
| `--seal-deep` | `#1691a1` | `#1e8f9c` | Its shadow side, the selected-row bar, the `<mark>` underline |
| `--accent` | `#094f56` | `#5fd4e2` | Focus rings, links — the accent when it must be read |
| `--accent-ink` | `#0b2a2e` | `#0a2226` | The words on the seal — 7.40 |
| `--accent-wash` | `rgba(62,198,214,.16)` | `rgba(95,212,226,.12)` | Selected row, read paragraph, selection |

### Semantic — verdicts only

| Token | Light | Dark | Meaning |
|---|---|---|---|
| `--good` | `#165134` | `#4fd39a` | Grades A–B; a verified quotation |
| `--warn` | `#624108` | `#e0b04a` | Grade C; quoted voice; a self-attack |
| `--bad` | `#872522` | `#ff8a84` | Grades D–F; a failure-mode chip |
| `--unchecked` | `#494944` | `#a09e97` | **Not checked.** Always dashed |

Each has a `-bg` at ~12% alpha of itself, so the tints sit correctly on stone *and* on paper.

---

## 3. Typography

| Token | Face | Used for |
|---|---|---|
| `--sans` | **Geist** 300–700, self-hosted | Everything the tool says |
| `--mono` | **Geist Mono** 400–600, self-hosted | Verbatim input and output: the brief, the plan, reports |
| `--serif` | Iowan Old Style / Palatino / Georgia | **The court's words, and only those** |

**Self-hosted, not a CDN.** The policy is `font-src 'self'`. Four latin/latin-ext `woff2` subsets,
82 KB, SIL OFL (`fonts/OFL.txt`), served by an allowlisted route rather than a directory mount.

**The serif is a voice marker, not a style.** A judgment's paragraphs, the claim under check, and the
inside of a verified quotation — where you are reading what somebody else wrote. Everywhere else is
Geist. Never set the tool's own words in it.

### Scale

Small and wide-set, like the reference. The page has almost no large type; hierarchy comes from
position, material and spacing.

| Role | Size / weight | Family |
|---|---|---|
| Wordmark | 14px / 600 | sans |
| Navigation | 12.5px / 500, active 600, `.01em` | sans |
| Eyebrow (one per stage) | 11px / 500, uppercase `.12em` | sans |
| Slot label, index heading | 10.5px / 600, uppercase `.10–.12em` | sans |
| Body | 14.5px / 1.55 | sans |
| Index row | 13px, citation 600 tabular | sans |
| Seal label | 11.5px / 650, balanced | sans |
| Judgment paragraph | 15.5px / 1.7 | **serif** |
| Claim, verified quote | 16px / 15.5px | **serif** |
| Fields, `pre` | 12.75px / 12.25px | mono |

---

## 4. Layout

| Region | Value |
|---|---|
| Slabs | 320px tiles, drawn with four 1px gradient seams (light then dark, offset 1px) and a grain overlay |
| Navigation | 64px, three-column grid: brand · centred tabs at 44px gap · status |
| Stage | eyebrow, then the frame at `max-width: 900px`, centred |
| Frame | padding `22px 22px 84px` — the bottom clears the seal that hangs over its edge |
| Seal | 132px, `bottom: calc(-66px + 22px)` of the frame, centred |
| Stage hint | `margin-top: 96px`, so it clears the seal rather than running behind it |
| Work | `grid`, `minmax(0,500px) / minmax(0,1fr)`, gap 30px; the index is sticky at `top: 24px` |

---

## 5. Elevation & Depth

Depth is *material*, not layering. The frame is recessed with six inset shadows (two bevel pairs, a
hairline, an inner cast shadow) and one outer. The paper slot lifts 1px off the recess. The seal casts
a coloured shadow — `rgba(22,145,161,.55)` — because a lit object lights what is under it. Stone
buttons have a one-pixel bevel and lift 1px on hover.

Nothing else has a shadow. There is no glassmorphism; the only blur on the page is none.

---

## 6. Shapes

**SHAPE LOCK — the stage is architectural, so it is square.** Frame `4px`, slot `3px`, controls
`4px`, grade mark `4px`. **Circles are the seal, the ring, the brand mark, the status pill, and the
chips — and they are exact circles.** Nothing is 8–16px rounded anywhere.

---

## 7. Components

### The seal
The primary action of each surface: `#go`, `#search`, `#build`. Aqua radial fill with a highlight, a
7px stone collar, a coloured cast shadow, and a slowly turning soft-light band (`turn`, 9s). Hover
lifts 3px and brightens the glow; press scales to .985. While working it is disabled, its label says
`Checking…`, and — on the check surface — the SVG ring around it fills from `progress` events. The
ring is driven by the `stroke-dashoffset` **attribute**, not a style, which is what keeps
`style-src 'self'` honest. Focus is a 3px teal outline at 12px offset, clear of the collar.

### Stone buttons (`.quiet`)
A small bevelled slab: gradient fill, `--edge` border, inset highlight, 1px drop. Lift on hover, press
in on active.

### Navigation tabs
Text, wide-set. The active tab has a 1px underline that grows from the left (`scaleX`, 320ms). The
active surface is written to `location.hash`. Panel tabs (`.tabs.plain`) are the same device at 12px.

### The index
An editorial strip. A heading rule in `--ink` with the summary on the right — `6 · 5 flagged · 0 clean
· 1 not checked`, each state with its dot, *not checked* with a dashed one — never collapsed into a
single count. Rows are `<button>`s in a three-column grid: mark · citation and parties · finding
chips. A hairline between rows; hover lifts to a faint white; selected shows a 2px `--seal-deep` bar
growing from the left and indents 6px. Rows rise 6px on arrival, staggered 45ms by `nth-child`.

**Chips carry the finding's words, never its number.**

### The document
Paper. Serif for the court's text, sans for the apparatus. The read paragraph takes the aqua wash and a
`--seal-deep` border; the verified sentence is `<mark>`ed with a wash and a 1px underline. Every panel
redraw rises in, because a redraw makes new nodes and the animation re-fires — no JS.

### Empty and loading
Empty: one plain sentence. Loading: a skeleton shaped like the rows about to arrive, and the seal
saying so.

---

## 8. Do's and Don'ts

### Do
- Set the court's words — and only those — in the serif.
- Ration semantic colour to verdicts.
- Keep the aqua a lit object: fills and glows with dark ink on them.
- Keep the focus ring.
- Add a class to `app.css` rather than a `style=` attribute.
- Say what a finding is, in words.

### Don't
- **Never add inline `<script>`, `<style>`, `style=` or `on*=`.** The CSP is `script-src 'self'` with
  no `unsafe-inline`, and `tests/test_hardening.py` fails the build if any appears. This is a security
  boundary wearing a style rule's clothes. SVG presentation attributes are fine; `style` is not.
- Never set text in `--seal`, or use it as a border.
- Never load a font, script or stylesheet from another origin — Google Fonts included.
- Never round anything that is not a circle past 4px.
- Never use green for "done" or red for "important".
- Never render *not checked* as a lighter failure, or fold it into a total.
- No second accent. No gradients beyond the seal and the loading sweep. No icon set, no emoji.
- Never interpolate server text into markup without `escape()`.

---

## 9. Responsive Behavior

| Breakpoint | Behaviour |
|---|---|
| ≥ 1061px | Index beside document; index sticky |
| ≤ 1060px | Index above document, static |
| ≤ 720px | Nav becomes brand + tabs, status hidden; frame tightens; seal 116px; index rows stack findings under the citation |

Verified in headless Chromium at 1440px and 390px, both themes: no console errors, no CSP violations,
no horizontal overflow, the skip link first in the tab order, the board focusable and operable.

---

## 10. Iteration Guide

1. Read `app.css` — the header comment carries the reasoning and the map from reference to product.
2. Change tokens, not literals. Solve contrast *before* writing CSS; the solver approach is in the
   commit history.
3. Add both themes at once.
4. Run `uv run pytest tests/test_hardening.py`.
5. **Look at it**, at 1440 and 390, light and dark. Every visual bug so far was invisible in the
   source: hidden buttons showing, a tab filling on hover, a hint running behind the seal.

---

## 11. Known Gaps

- **The reference is animated; this is mostly still.** The seal turns, rows rise, tabs underline —
  MOTION 6 — but there is no scroll-driven motion and no page transition between surfaces. Both are
  the next step, and both need `prefers-reduced-motion` to be honoured as they are today.
- **No custom cursor.** The reference has one. Deliberately skipped: it is an accessibility trade
  nobody asked for yet.
- **Colour and border style alone** separate a failure chip from *needs review*. A glyph would be safer.
- **`backdrop-filter` is gone**, so this gap closed — but the stone grain is an SVG filter and has not
  been profiled on a low-end device.
- **No automated axe or Lighthouse pass.** The hand-written checks cover what was found wrong, which is
  not coverage.
