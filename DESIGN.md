# DESIGN.md — OrderOrder

A design system in the [Stitch DESIGN.md](https://stitch.withgoogle.com/docs/design-md/overview/)
format, so that any agent asked to build or change this interface reads one document rather than
guessing from the code.

**This describes the system already implemented**, not an aspiration. Every token below is live in
`src/orderorder/web/static/app.css`; if the two disagree, the stylesheet is the fact and this file is
the bug. Every colour pair is asserted in `tests/test_hardening.py`, both themes.

> **Fourth design, and the first built to a brand rather than to a mood.** The first was warm paper,
> oxblood and a serif — the palette the taste skill bans by hex. The second was cool greys and cobalt —
> competent and indistinguishable from every tool that year. The third copied a CGI studio site's
> props (stone, a glossy porthole) in CSS, which reads cheaper than doing nothing. The reference that
> fixed it is a law firm's identity by Redis Agency, *L'escalier*: flat cobalt, coral and cream colour
> blocks, a high-contrast display serif over a clean grotesque, single-weight hand-drawn lines, giant
> serif numerals, rounded cards on colour, and a staircase as the shape device. It fits because every
> competitor in legal software is navy and gold and cold, and because **a grade from A to F is a
> staircase**. What was wrong before is kept here on purpose.

---

## 1. Visual Theme & Atmosphere

**Warm, confident, human — and it still means business.** Large flat colour blocks with generous
radius; a display serif that speaks; a grotesque that works; hand-drawn lines that make it feel made by
a person. Editorial rather than SaaS. It should feel like a firm you would trust with a matter, not a
dashboard you would trust with a metric.

Each device is the product, not decoration:

| device | what it is here |
|---|---|
| **the colour block** | the surface's voice: cobalt for checking, cream for finding, ink for drafting |
| **the folder** | a card with a tab, because a brief arrives in one |
| **the scribble** | the underline a person draws under the thing that matters |
| **the numeral** | the count, set the way the reference sets section numbers — huge, serif, red |
| **the staircase** | the mark, and the stepped mass the footer rises from; A to F |

**Density:** hero airy, work dense. **Mood words:** warm, exact, editorial, assured.
**Never:** navy-and-gold, glassy, stone, gradients, cold SaaS grey.

**Dials** (taste-skill convention): `DESIGN_VARIANCE 8 · MOTION_INTENSITY 6 · VISUAL_DENSITY 4`.

---

## 2. Colors

Three rules, in priority order.

1. **Colour means a finding.** Green, amber and red are reserved for verdicts. The brand's own red is
   therefore *the verdict red*: a flagged citation is the red thing on the page, and the only
   decorative red is the count of them.
2. **Cobalt is the brand.** The mark, the primary button, links, focus, the selected row, the tab
   scribble, the footer. Coral and cream are the other two blocks; nothing else is introduced.
3. **Three states, three treatments.** *Not checked* is a dashed neutral — never a paler red, never
   folded into a total.

### The blocks

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#f3ece5` | `#0f1236` | Cream page / navy page |
| `--surface` | `#ffffff` | `#171b48` | Cards, the folder, the status pill |
| `--surface-2` | `#e9ebfb` | `#1e2358` | Cobalt tint: inset fields, hover |
| `--accent` | `#2b34d6` | `#8f97ff` | Cobalt. The brand. |
| `--accent-press` | `#1f27b3` | `#aab0ff` | Hover and press |
| `--accent-ink` | `#ffffff` | `#0f1236` | Text **on** cobalt — 8.19 |
| `--accent-soft` | `rgba(43,52,214,.10)` | `rgba(143,151,255,.14)` | Selected row, read paragraph, hover |
| `--coral` | `#ef3b5c` | `#ff7d93` | The numeral and large type only — 3.85 on white |
| `--coral-deep` | `#d51135` | `#ff7d93` | The same red where it must be read — 4.53 |

The cobalt hero block stays `#2b34d6` with cream text in **both** themes: it is a brand colour, not a
surface, and it does not invert.

### Ink

| Token | Light | Dark | Use |
|---|---|---|---|
| `--ink` | `#141626` | `#f3ece5` | Primary text |
| `--ink-2` | `#3b3e55` | `#cfcad9` | Navigation, secondary prose |
| `--muted` | `#5f627a` | `#a9a5bb` | Hints, captions |
| `--faint` | `#676a80` | `#9d99b0` | Paragraph labels, placeholders |
| `--line` | `rgba(20,22,38,.12)` | `rgba(243,236,229,.12)` | Dividers — decorative, no contrast duty |
| `--edge` | `#8286a4` | `#616795` | **Control boundaries** — 3.04 |

### Semantic — verdicts only

| Token | Light | Dark | Meaning |
|---|---|---|---|
| `--good` | `#1f7a4c` | `#4fd39a` | Grades A–B; a verified quotation |
| `--warn` | `#975e0a` | `#e9b949` | Grade C; quoted voice; a self-attack |
| `--bad` | `#d51135` | `#ff7d93` | Grades D–F; a finding chip |
| `--unchecked` | `#5f627a` | `#a9a5bb` | **Not checked.** Always dashed |

Each has a `-bg` at ~12% alpha of itself, so the tints sit on cream and on white alike.

---

## 3. Typography

| Token | Face | Used for |
|---|---|---|
| `--display` | **Playfair Display** 400–900 + italic, self-hosted | Headlines, the wordmark, the numeral, the footer lead, grade letters |
| `--sans` | **Geist** 300–700, self-hosted | Everything the tool says |
| `--mono` | **Geist Mono** 400–600, self-hosted | Verbatim input and output |
| `--serif` | Iowan Old Style / Palatino / Georgia | **The court's words**: judgment paragraphs, the claim, a verified quote |

**Two serifs, two jobs, never swapped.** Playfair is the *brand voice*: high-contrast, editorial,
present only in headlines and the numeral. The Palatino stack is the *reading voice*: it marks text
somebody else wrote. A judgment paragraph in Playfair, or a headline in Palatino, is wrong.

**Self-hosted, not a CDN.** The policy is `font-src 'self'`. Six latin `woff2` subsets, 158 KB total,
both fonts under the SIL Open Font License (`fonts/OFL.txt`, `fonts/OFL-Playfair.txt`), served by an
allowlisted route rather than a directory mount. Playfair is on the taste skill's approved serif list;
the brief names a serif, so the serif is earned.

### Scale

| Role | Size / weight | Family |
|---|---|---|
| Headline | `clamp(40px, 4.6vw, 66px)` / 500, `-.02em`, 1.02 | display; one italic word per headline, same family |
| Wordmark | 20px / 600 | display |
| Numeral | 88px / 500, `-.03em` | display, `--coral` |
| Footer lead | 22px | display |
| Eyebrow | 11.5px / 600, uppercase `.12em` | sans |
| Navigation | 13.5px / 500, active 600 | sans |
| Lede | 15.5px / 1.6, `max-width: 46ch` | sans |
| Body | 15px / 1.55 | sans |
| Index row | 13.5px, citation 600 tabular | sans |
| Grade mark | 15px / 600 in a 30px square | display |
| Judgment paragraph | 15.5px / 1.7 | serif |
| Fields, `pre` | 12.75px / 12.25px | mono |

---

## 4. Layout

| Region | Value |
|---|---|
| Navigation | 72px, three-column grid: brand · centred tabs at 34px gap · status |
| Page | `max-width: 1400px`, padding `14px 40px 96px` |
| Hero | `grid`, `1.05fr / .95fr`, gap 24px, `min-height: 560px`; block left, folder right |
| Block | radius 28px, padding `56px 56px 52px`, content vertically centred |
| Folder | tab `12px 24px 10px` offset 22px; body radius 22px, padding `22px 24px 20px` |
| Work | `grid`, `minmax(0,520px) / minmax(0,1fr)`, gap 24px, `margin-top: 40px`; index sticky at 20px |
| Card | radius 28px, padding `28px 30px` |
| Footer | stepped SVG edge 64px, then cobalt at `36px 40px 56px`, three columns |

---

## 5. Elevation & Depth

One shadow, tinted to the ink, on cards and the folder: `0 1px 2px .05, 0 24px 48px -32px .28`. The
primary button casts a cobalt shadow (`0 10px 24px -14px var(--accent)`) that deepens on hover, because
the one thing you press should look like it can be pressed. Nothing else has a shadow. Depth is
otherwise flat colour against flat colour, which is the reference's whole manner.

---

## 6. Shapes

**SHAPE LOCK — soft.** Blocks and cards `28px`, the folder `22px`, fields `12px`, the grade mark `9px`,
controls and chips full pill. **Nothing is sharp except the staircase**, which is the point of it.

The staircase appears exactly three times: the mark (a three-step path in a cobalt square), the footer
edge (a stepped cobalt mass rising from the bottom), and — implicitly — the grade letters, which are
its steps. Do not add a fourth without a reason as good as those.

---

## 7. Components

### The colour block
The hero's left half and the surface's voice. **Cobalt** with cream text for *Check*; **cream** with
ink and a coral scribble for *Find*; **ink** with cream and a coral scribble for *Draft*. Contains an
eyebrow, the headline, the scribble, the lede, and a `doodle` SVG of two or three loose curves at 1.6px
that draw on over 2.4s and stay. The block rises in over .8s.

### The headline
Playfair, balanced, `max-width: 14ch`, one italic word set in the same family. Words are wrapped in
`.w` spans and rise in sequence, 70ms apart. The scribble beneath is an SVG path drawn by
`stroke-dashoffset` over 1.1s, starting once the words have landed.

### The folder
A tab (`label`, uppercase, cobalt) sitting on a card. The field inside is mono on cream with an `--edge`
border; focus turns the border cobalt and adds a 4px soft ring. Controls sit in two rows: actions,
then the model toggle and progress.

### Buttons
**Primary:** cobalt pill, white text, 12×22px, cobalt shadow; the arrow nudges 4px right on hover and
the button lifts 1px. Working state writes `Checking…` into the label and takes `cursor: progress`.
**Quiet:** transparent pill with an `--edge` border; hover fills with the cobalt tint and turns the text
cobalt. Focus is a 2px cobalt outline at 3px offset on everything — **never remove it.**

### Navigation tabs
Text at 13.5px. The active tab carries a **hand-drawn underline** — an SVG scribble in a data URI —
that grows from the left over .38s. The active surface is written to `location.hash` and to
`body[data-surface]`. Panel tabs (`.tabs.plain`) are the same device at 13px inside a card.

### The tally
A giant coral numeral beside three lines — `5 flagged · 0 clean · 1 not checked`, each with its dot,
*not checked* with a dashed one — over a 1px ink rule. The numeral **rolls up** to its value over 600ms
with an ease-out cubic; under `prefers-reduced-motion` it appears. The total is deliberately not
repeated as a fourth line: the three states *are* the total.

### The index
Rows are `<button>`s in a three-column grid: grade mark · citation and parties · finding chips. A
hairline between rows; hover tints cobalt; selected indents 6px and grows a 3px cobalt bar from the
left. Rows rise on arrival, staggered 50ms by `nth-child`. **Chips carry the finding's words, never its
number.**

### The grade mark
A Playfair letter in a 30px soft square: A/B green, C amber, D–F red, and **dashed neutral when checks
could not run**.

### The document
A card. Serif for the court's text, sans for the apparatus. The read paragraph takes a 3px cobalt bar
and the cobalt tint; the verified sentence is `<mark>`ed with the tint and a 2px cobalt underline.
Every panel redraw rises in — a redraw makes new nodes, so the animation re-fires with no JS.

### Footer
The staircase edge, then a cobalt block: a Playfair lead, the three-state sentence, the attribution.

### Empty and loading
Empty: one plain sentence in `--muted`; the numeral shows an en dash. Loading: a skeleton shaped like
the rows about to arrive, and the button saying so.

---

## 8. Do's and Don'ts

### Do
- Set headlines in Playfair and the court's words in Palatino; never the reverse.
- One italic word per headline, same family — that is the emphasis device.
- Keep coral for the numeral and for findings. It is the verdict red.
- Give *not checked* a dashed neutral and its own line in the tally.
- Draw lines by hand: an SVG path at one weight, with `stroke-dashoffset` if it should arrive.
- Keep the focus ring, and the 46ch measure on prose.

### Don't
- **Never add inline `<script>`, `<style>`, `style=` or `on*=`.** The CSP is `script-src 'self'` with
  no `unsafe-inline`, and `tests/test_hardening.py` fails the build if any appears. SVG presentation
  attributes are fine; `style` is not.
- Never load a font, script or stylesheet from another origin — Google Fonts included.
- Never introduce a fourth colour, or use cobalt for a verdict.
- Never set body text in `--coral` — it is 3.29 on cream. Use `--coral-deep`.
- Never round a corner under 9px or over 28px, except a pill.
- No gradients, no glass, no shadows beyond the two named, no icon set, no emoji.
- Never interpolate server text into markup without `escape()`.

---

## 9. Responsive Behavior

| Breakpoint | Behaviour |
|---|---|
| ≥ 1001px | Hero two-up; index beside document, sticky |
| ≤ 1000px | Hero stacks block over folder; work stacks |
| ≤ 720px | Nav becomes brand + scrolling tabs, status hidden; block padding 34/26, headline 38px, radius 22px; numeral 64px; finding chips stack under the citation |

Verified in headless Chromium at 1440px and 390px, both themes: no console errors, no CSP violations,
no horizontal overflow, the skip link first in the tab order, the board focusable and operable, the
tab state reaching the URL.

---

## 10. Iteration Guide

1. Read `app.css` — the header comment carries the reasoning and what the first three designs got wrong.
2. Change tokens, not literals. Solve contrast *before* writing CSS; the solver is in the commit history.
3. Add both themes at once, and remember the cobalt block does not invert.
4. Run `uv run pytest tests/test_hardening.py`: contrast in both themes, no inline script or style, no
   `on*=`, every class styled, every id the script reaches for present.
5. **Look at it**, at 1440 and 390, light and dark, and at the loading state. Every visual bug in this
   project's history was invisible in the source.

---

## 11. Known Gaps

- **The reference is a motion piece; this is a page with motion.** Words rise, lines draw, the numeral
  rolls, rows stagger — MOTION 6. There is no transition *between* surfaces; switching tabs cuts. A
  colour-block crossfade keyed on `body[data-surface]` is the next step, and the attribute is already
  there for it.
- **No photography.** The reference leans on warm portraits of lawyers at work; this product has none
  and should not fake them. If real photography arrives, it belongs on the cream block, not the cobalt.
- **Colour and border style alone** separate a failure chip from *needs review*. A glyph would be safer.
- **The doodles are three fixed paths.** They do not vary per visit or per surface beyond what is
  hand-drawn; a small library of curves would keep them from becoming furniture.
- **No automated axe or Lighthouse pass.** The hand-written checks cover what was found wrong, which is
  not the same as coverage.
