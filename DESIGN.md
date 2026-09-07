# DESIGN.md — OrderOrder

A design system in the [Stitch DESIGN.md](https://stitch.withgoogle.com/docs/design-md/overview/)
format, so that any agent asked to build or change this interface reads one document rather than
guessing from the code.

**This describes the system already implemented**, not an aspiration. Every token below is live in
`src/orderorder/web/static/app.css`; if the two disagree, the stylesheet is the fact and this file is
the bug. Every colour pair is asserted in `tests/test_hardening.py`, both themes.

> **Built to a brand, then stripped of everything that decorated it.** The reference is a law firm's
> identity by Redis Agency, *L'escalier*: flat cobalt, coral and cream colour blocks, a high-contrast
> display serif over a clean grotesque, giant serif numerals, rounded cards on colour, and a staircase
> as the shape device. It fits because every competitor in legal software is navy and gold and cold,
> and because **a grade from A to F is a staircase**. The first pass at it still read as machine-made,
> and the reasons were specific: floating curves that meant nothing, an eyebrow-headline-lede stack,
> words rising one at a time, two identical cards, a shimmering skeleton, a hand-drawn scribble under
> the active tab, a green-dot status pill. Each is gone. What replaced them is three-dimensional and
> each piece is the subject.

---

## 1. Visual Theme & Atmosphere

**Warm, confident, human — and it still means business.** Large flat colour blocks with generous
radius; a display serif that speaks; a grotesque that works. Editorial rather than SaaS. It should feel
like a firm you would trust with a matter, not a dashboard you would trust with a metric.

Nothing on the page is decoration. The things that stand in three dimensions are the product:

| object | where | what it does |
|---|---|---|
| **the mark** | the corner of the bar | the staircase, in the projection the verdict panel uses; climbs a pixel a step under the pointer |
| **the bundle** | the check block | a stack of pleadings that leans toward the pointer; as the check runs, read pages are set aside |
| **the shelf** | the find block | six volumes of reports; while a search runs they come down one after another; when it finds something, one stays out |
| **the tome** | the draft block | the submission being bound; an index tab comes out for each sentence — cobalt with an authority behind it, coral without |
| **the stamp** | the index | a grade lands on its row from above, with a shadow that blooms and settles |
| **the stair** | the verdict panel | six isometric steps, F to A; the marker stands on the step earned — or off the stair if not checked |

**Density:** hero airy, work dense. **Mood words:** warm, exact, editorial, assured.
**Never:** navy-and-gold, glassy, stone, gradients, cold SaaS grey, decorative squiggles, eyebrows,
status dots.

**Dials** (taste-skill convention): `DESIGN_VARIANCE 8 · MOTION_INTENSITY 6 · VISUAL_DENSITY 4`.

---

## 2. Colors

Three rules, in priority order.

1. **Colour means a finding.** Green, amber and red are reserved for verdicts. The brand's own red is
   therefore *the verdict red*: a flagged citation is the red thing on the page, and the only other red
   is the count of them, the marker on the stair, and the tab on a sentence with no authority.
2. **Cobalt is the brand.** The mark, the primary button, links, focus, the selected row, the binder
   clip, the binding of the tome, the spines on the shelf, the stair, the footer. Coral and cream are the
   other two blocks. **Ink is the chrome**: the thumb of the surface control and the line under an open
   panel are ink, so the bar never competes with the block beneath it.
3. **Three states, three treatments.** *Not checked* is a dashed neutral — never a paler red, never
   folded into a total, and on the stair it stands *off* the steps.

### The blocks

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#f3ece5` | `#0f1236` | Cream page / navy page; the bar; the label on the thumb |
| `--surface` | `#ffffff` | `#171b48` | The folder, the document card, the pill of the surface control |
| `--surface-2` | `#e9ebfb` | `#1e2358` | Cobalt tint: inset fields, hover |
| `--accent` | `#2b34d6` | `#8f97ff` | Cobalt. The brand. |
| `--accent-press` | `#1f27b3` | `#aab0ff` | Hover and press; a bound tab |
| `--accent-deep` | `#1a2199` | `#1a2199` | The shaded face of anything cobalt in three dimensions |
| `--accent-ink` | `#ffffff` | `#0f1236` | Text **on** cobalt — 8.19 |
| `--accent-soft` | `rgba(43,52,214,.10)` | `rgba(143,151,255,.14)` | Selected row, read paragraph, the pinpoint on the top page |
| `--coral` | `#ef3b5c` | `#ff7d93` | The numeral, the marker, the tab with no authority — large or non-text only; 3.85 on white |
| `--coral-deep` | `#d51135` | `#ff7d93` | The same red where it must be read — 4.53 |
| `--paper` / `--paper-edge` | `#fbf8f3` / `#e6dfd5` | `#f3ece5` / `#d9d1c6` | A page in the bundle, the top of a volume, the plank |
| `--tome` / `--tome-edge` | `#fbf8f3` / `#ddd4c8` | `#ffffff` / `#d9d1c6` | The tome's pages — white in the dark, because the draft block is cream there |

The cobalt hero block stays `#2b34d6` with cream text in **both** themes: it is a brand colour, not a
surface, and it does not invert. The mark is brand colours too, and is identical in both themes.

### Ink

| Token | Light | Dark | Use |
|---|---|---|---|
| `--ink` | `#141626` | `#f3ece5` | Primary text; the thumb; the panel underline; two of the volumes |
| `--ink-2` | `#3b3e55` | `#cfcad9` | Navigation, secondary prose |
| `--muted` | `#5f627a` | `#a9a5bb` | Hints, captions, the readout in the bar |
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

---

## 3. Typography

| Token | Face | Used for |
|---|---|---|
| `--display` | **Playfair Display** 400–900 + italic, self-hosted | Headlines, the wordmark, the numeral, the footer lead, grade letters |
| `--sans` | **Geist** 300–700, self-hosted | Everything the tool says |
| `--mono` | **Geist Mono** 400–600, self-hosted | Verbatim input and output; the readout in the bar |
| `--serif` | Iowan Old Style / Palatino / Georgia | **The court's words**: judgment paragraphs, the claim, a verified quote |

**Two serifs, two jobs, never swapped.** Playfair is the *brand voice*, in headlines and the numeral.
The Palatino stack is the *reading voice*; it marks text somebody else wrote.

**Self-hosted, not a CDN.** `font-src 'self'`. Six latin `woff2` subsets, 158 KB, both under the SIL
Open Font License (`fonts/OFL.txt`, `fonts/OFL-Playfair.txt`), served by an allowlisted route.

### Scale

| Role | Size / weight | Family |
|---|---|---|
| Headline | `clamp(40px, 4.4vw, 62px)` / 500, `-.02em`, 1.04, `max-width: 13ch` | display; one italic word, same family |
| Wordmark | 21px / 600, `-.015em` | display |
| Numeral | 88px / 500, `-.03em` | display, `--coral` |
| Footer lead | 22px | display |
| Surface control | 13px / 600 | sans |
| Readout | 11.5px, tabular | mono, `--muted` |
| Lede | 15px / 1.6, `max-width: 44ch` | sans |
| Body | 15px / 1.55 | sans |
| Index heading | 11.5px / 600, uppercase `.12em`, cobalt | sans |
| Index row | 13.5px, citation 600 tabular | sans |
| Grade mark | 15px / 600 in a 30px square | display |
| Judgment paragraph | 15.5px / 1.7 | serif |
| Fields, `pre` | 12.75px / 12.25px | mono |

Headlines are three or four words. *Every citation, verified.* The lede does the explaining.

---

## 4. Layout

| Region | Value |
|---|---|
| Bar | 72px, **sticky**, page colour, three-column grid: lockup · surface control · readout; a hairline appears under it once the page has moved (`body[data-scrolled]`) |
| Page | `max-width: 1400px`, padding `14px 40px 96px` |
| Hero | `grid`, `1.05fr / .95fr`, gap 24px, `min-height: 580px`; block left, folder right |
| Block | radius 28px, padding `56px 56px 52px`, `overflow: hidden`; the object sits in its lower right |
| Folder | tab `12px 24px 10px` offset 22px; body radius 22px, padding `22px 24px 20px` |
| Work | `grid`, `minmax(0,520px) / minmax(0,1fr)`, gap 40px, `margin-top: 48px`; the index is sticky at 92px, under the bar |
| Index | **not a card** — a ruled list on the page, heading in cobalt, a 1.5px ink rule under the tally |
| Document | the one card: radius 28px, padding `26px 30px 30px`, with the stair top-right of its head |
| Footer | stepped SVG edge 64px, then cobalt at `36px 40px 56px`, three columns |

---

## 5. Elevation & Depth

Two kinds. **Flat depth**, the reference's manner: colour against colour, one tinted shadow on the
folder and the document card, a cobalt shadow under the primary button. And **real depth**, built in
CSS 3D, in the objects only:

- **The bundle** sits in a 1100px perspective, the stack rotated `54deg` on X and `-22deg` on Z. Six
  pages, each 5px above the last and offset in the plane so their edges peek out; lower pages a shade
  darker. A cobalt binder clip grips the top edge.
- **The shelf** is a 1200px perspective, the row rotated `12deg` on X and `-24deg` on Y, so the spines,
  the page tops and the last cover show. Each volume is three faces of a box — the spine, the top rotated
  back from its upper edge, the cover rotated back from its right edge — and the neighbours hide every
  cover but the last, which is what a shelf does. Volumes are 34–46px wide and 168–190px tall, never
  uniform. A pulled volume comes `52px` forward and turns `-12deg`.
- **The tome** lies the way the bundle lies (`56deg` X, `16deg` Z). The top page is a face lifted
  `16px`; the two edges you can see are faces dropped from it, striped like the ends of pages; the
  binding is a 20px cobalt strip down the left. Index tabs sit `1px` under the top page, so the part
  inside the block is covered and the part outside is not.
- **The mark** and **the stair** are oblique projection, not perspective: a front face, a top face
  `skewX(-45deg)`, a side face `skewY(-45deg)`. The mark is the same construction in an SVG.
- **The stamp** is a keyframe on the grade mark: from 14px above, 135%, `-6deg`, with a cast shadow,
  to rest — 550ms, inheriting the row's stagger.

Every object leans up to `±5deg` / `±4deg` toward the pointer through two custom properties, and the
bundle and the tome breathe 6px over 7s. Nothing else casts a shadow or leaves the plane.

---

## 6. Shapes

**SHAPE LOCK — soft.** Blocks and cards `28px`, the folder `22px`, fields `12px`, the grade mark `9px`,
controls, chips and the surface control full pill. **Nothing is sharp except the staircase**, which is
the point of it — and the three-dimensional objects, which are things and keep their corners.

The staircase appears four times: the mark, the stair in the verdict panel, the footer edge, and the
favicon. Do not add a fifth without a reason as good as those.

---

## 7. Components

### The bar
Sticky, in the page colour, with a hairline that arrives on scroll. **Lockup:** the mark (30px, cobalt
rounded square, the stair in cream with one deep side) and the wordmark. **Surface control:** three
equal segments on a white pill with a hairline border, and one thumb in ink that slides to the segment
you are on. Equal segments are what let the thumb be placed by rule — a third of the width, moved one
or two of its own widths — with nothing measured or written by script. The thumb squashes as it
travels. Labels are one verb each (*Check · Find · Draft*); the full phrase is the accessible name.
**Readout:** what is loaded, in mono, no pill, no dot: `9,424 judgments · model configured`.

### Changing surface
A crossfade, not a cut, and the whole of it is three attributes on `<body>`. `data-surface` moves the
thumb at once. `data-leaving` fades the outgoing block's words, its object, the folder and the work,
160ms. Then the sections swap, `data-prev` is set to the surface before, and the stylesheet starts the
incoming block in that surface's colour (`from-cobalt`, `from-cream`, `from-ink`) and turns it into its
own over 550ms while the words, the folder and the work fade in on staggered delays. On first paint,
and on arrival from a link, the block rises instead. Under `prefers-reduced-motion` the swap is
immediate. The surface is the URL's hash, both ways: a tab writes it, and the back button or a hash
typed by hand reads it.

### The colour block
The hero's left half and the surface's voice: **cobalt** for *Check*, **cream** for *Find*, **ink** for
*Draft*. Headline, lede, and the surface's object. No eyebrow.

### The bundle
`#bundle[data-flipped]`, `0`–`5`. As citations are found, each fifth **sets the next page aside**: it
slides to the block's empty side, tilts, and fades to 62%, the earlier pages travelling further so
they fan. Pages are never turned over: a turned page is face-down and gone.

### The shelf
`#shelf[data-state]`: `idle`, `searching`, `found`. Searching runs `browse` on every volume with a
400ms stagger — each comes forward and goes back, one after another, on a 2.4s loop. Found leaves the
third volume out. A search that returns nothing puts them all back.

### The tome
`#book[data-state]`: `idle`, `drafting`, `done`. While drafting, the lines on the top page write
themselves top to bottom on a 2.2s loop (a mask-size animation). Each tab is `.tab.out` once its
sentence has been bound, with `data-state="bound"` (cobalt) or `"none"` (coral) read from the
binding's `usable`. Eight tabs; a longer plan fills them.

### The tilt
The one place JavaScript writes a style: `--tx` and `--ty` on each object through `style.setProperty`,
which the Content-Security-Policy permits (it governs `style=` attributes and stylesheets, not CSSOM
property writes) and which `test_nothing_generated_carries_an_inline_style_either` distinguishes from
an attribute. Off for coarse pointers and under `prefers-reduced-motion`.

### The folder
A tab (`label`, uppercase, cobalt) on a card. Mono field on cream with an `--edge` border; focus turns
it cobalt with a 4px soft ring. Two rows of controls: actions, then the model toggle and progress.

### Buttons
**Primary:** cobalt pill, white text, cobalt shadow; the arrow nudges 4px on hover; lifts 1px. Working
state writes `Checking…` into the label. **Quiet:** transparent pill with an `--edge` border; hover
fills with the cobalt tint. Focus is a 2px cobalt outline at 3px offset — **never remove it.**

### Panel tabs
Inside the document card: text over a hairline, a 2px ink line under the open one, growing from the
left. Not the surface control, and not styled with it.

### The tally
A giant coral numeral beside three lines — `5 flagged · 0 clean · 1 not checked`, each with its dot,
*not checked* with a dashed one — over a 1.5px ink rule. The numeral rolls up over 600ms. The total is
not repeated as a fourth line.

### The index
Rows are `<button>`s in a three-column grid: grade mark · citation and parties · chips. Hairlines
between; hover tints cobalt; selected indents 6px and grows a 3px cobalt bar. Rows rise, staggered 60ms,
and each **grade lands as a stamp** on its row's delay. **Chips carry the finding's words, never its
number.**

### The stair
`#stair[data-grade][data-partial]` in the document card's head, beside the panel tabs. The marker is
coral for D–F, amber for C, green for A–B, and it slides between steps over 600ms. When a citation was
*not checked*, `data-partial="1"`: the marker stands to the left of the first step, hollow and dashed,
and the step tops dim. Placement is by fixed rule per grade — six rules, no arithmetic in the script.

### The document
Serif for the court's text, sans for the apparatus. The read paragraph takes a 3px cobalt bar and the
tint; the verified sentence is `<mark>`ed with a 2px cobalt underline.

### Empty and loading
Empty: one plain sentence in `--muted`; the numeral shows an en dash; the stair has no marker. Loading:
five quiet hairlines where rows will be — **no shimmer** — and on every surface the object doing the
talking: pages set aside, volumes coming down, lines writing themselves.

---

## 8. Do's and Don'ts

### Do
- Set headlines in Playfair and the court's words in Palatino; never the reverse.
- Keep headlines to three or four words. Explain in the lede.
- Keep coral for the numeral, the marker, findings, and the tab on a sentence with none. It is the
  verdict red.
- Keep ink for the chrome — the thumb, the panel line — and cobalt for the brand and the primary action.
- Give *not checked* a dashed neutral, its own line in the tally, and a place off the stair.
- Keep the focus ring, and the 44ch measure on prose.
- Build a new object from faces, in the same perspective family, and give it a state that the product
  actually has. An object with no state is decoration.

### Don't
- **Never add inline `<script>`, `<style>`, `style=` or `on*=`.** The CSP is `script-src 'self'` with
  no `unsafe-inline`, and `tests/test_hardening.py` fails the build if any appears. The only style the
  script writes is the two tilt properties, through the CSSOM.
- **No decoration.** No floating curves, no eyebrows, no words rising one at a time, no shimmer, no
  scribbles, no status dots. If a thing on the page is not the product, remove it.
- Never load a font, script or stylesheet from another origin.
- Never introduce a fourth colour, or use cobalt for a verdict.
- Never set body text in `--coral`. Use `--coral-deep`.
- Never turn a page over. Set it aside.
- Never measure the thumb in script. The segments are equal so that the rule can place it.
- Never interpolate server text into markup without `escape()`.

---

## 9. Responsive Behavior

| Breakpoint | Behaviour |
|---|---|
| ≥ 1001px | Hero two-up; index beside document, sticky under the bar |
| ≤ 1000px | Hero stacks block over folder; work stacks |
| ≤ 720px | Bar 64px: the mark alone, the surface control at the right, the readout hidden; the block grows a 210px band at its foot so the object, scaled to 72%, has room under the words rather than over them; headline 38px; numeral 64px; the stair moves under the panel tabs; chips stack under the citation |

Verified in headless Chromium at 1440px and 390px, both themes: no console errors, no CSP violations,
no horizontal overflow, the skip link first in the tab order, the board focusable and operable, the
thumb at `100%` on *Find*, the shelf `found` after a search, the tome `done` with its tabs out.

---

## 10. Iteration Guide

1. Read `app.css` — the header comment carries the reasoning and the list of what was cut.
2. Change tokens, not literals. Solve contrast *before* writing CSS.
3. Add both themes at once; the cobalt block and the mark do not invert.
4. Run `uv run pytest tests/test_hardening.py`: contrast, no inline script or style, no `on*=`, every
   class styled, every id the script reaches for present.
5. **Look at it**, at 1440 and 390, light and dark, idle and mid-state and finished. The shelf's first
   render had its plank running into the block's rounded corner, the tome's first render lay across the
   lede, and at 390px both sat on top of the words; nothing but a render could have said so.

---

## 11. Known Gaps

- **Colour and border style alone** separate a failure chip from *needs review*. A glyph would be safer.
- **The stair's grade rules are fixed per letter.** A seventh grade would need a seventh rule.
- **The shelf always leaves the third volume out.** Which volume is the found one carries no meaning
  yet; it could be the one whose position matches the result's rank.
- **Eight tabs on the tome.** A plan with more sentences than that fills them and stops.
- **No automated axe or Lighthouse pass.** The hand-written checks cover what was found wrong, which is
  not the same as coverage.
