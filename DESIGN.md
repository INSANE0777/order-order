# DESIGN.md — OrderOrder

A design system in the [Stitch DESIGN.md](https://stitch.withgoogle.com/docs/design-md/overview/)
format, so that any agent asked to build or change this interface reads one document rather than
guessing from the code.

**This describes the system already implemented**, not an aspiration. Every token below is live in
`src/orderorder/web/static/app.css`; if the two ever disagree, the stylesheet is the fact and this
file is the bug. The reasoning behind each rule is in that file's header comment.

---

## 1. Visual Theme & Atmosphere

**A law report, not a dashboard.** The reference is the printed page an advocate already trusts: a
Supreme Court Report — set in a serif, ruled with hairlines, generous in the margin, severe about
hierarchy. Restrained, quiet, and dense with text rather than with chrome.

This is not decoration. The product's entire claim is that it will not overstate: it separates
*supported*, *checked and not supported*, and *not checked*, and refuses to collapse them. An
interface of gradient cards, progress rings and confident green ticks would be overstating before it
had said anything. The design has to look like something that abstains.

**Density:** comfortable-to-dense. Long legal text is the content; it needs line length and leading,
not padding.
**Mood words:** considered, printed, sober, exact. **Never:** playful, energetic, futuristic, sleek.

---

## 2. Colors

Three rules govern the palette, in priority order.

1. **Ink on paper, not text on a surface.** The light theme is warm bone, never `#fff` — a report is
   printed on stock, and a pure-white field beside a serif reads clinical.
2. **Colour means a finding.** Green, amber and red are reserved for grades and flags. Nothing
   decorative may borrow them, or red stops meaning *this citation is wrong*.
3. **Three states, three treatments.** *Not checked* is not a weaker failure and never gets a paler
   red. It gets a dashed, muted badge of its own — provisional, not bad.

### Surface & ink

| Token | Light | Dark | Use |
|---|---|---|---|
| `--paper` | `#f7f4ee` | `#14120f` | Page ground, inset fields |
| `--paper-raised` | `#fffdf8` | `#1c1a16` | Cards, masthead |
| `--ink` | `#1a1714` | `#ece7dd` | Body text |
| `--ink-soft` | `#45403a` | `#cbc4b8` | Secondary prose |
| `--muted` | `#6b645b` | `#9a9287` | Captions, hints |
| `--faint` | `#746e65` | `#8b8377` | Labels, empty states |
| `--rule` | `#ddd6c9` | `#2c2822` | Decorative hairlines and dividers |
| `--rule-strong` | `#c6bdac` | `#413b32` | Heavier dividers |
| `--edge` | `#99896b` | `#716657` | **Control boundaries**: field and quiet-button borders |

`--rule` and `--edge` look similar and are not interchangeable. A divider carries no information and
may be as light as it likes; the edge that tells you a thing is a control must clear 3:1, which
`--rule-strong` did not (1.83). Use `--edge` on anything you can type in or press.

### Brand

| Token | Light | Dark | Use |
|---|---|---|---|
| `--seal` | `#7b2233` | `#c9697a` | Oxblood — the colour of a bound reporter's spine |
| `--seal-soft` | `#a33c4e` | `#d98a98` | Hover only |

Oxblood appears on: the wordmark and its short rule, the active tab underline, the primary button,
the read-paragraph marker, selection. **Nowhere else.**

### Semantic — findings only

| Token | Light fg / bg | Dark fg / bg | Meaning |
|---|---|---|---|
| `--good` | `#2f6b45` / `#e6efe7` | `#7fbf95` / `#1b2a20` | Grades A–B; a verified quotation |
| `--warn` | `#8a5a12` / `#f6eddb` | `#d3a253` / `#2a2216` | Grade C; a quoted-voice marker; a self-attack |
| `--bad` | `#9d2f28` / `#f6e5e2` | `#e08b82` / `#2c1c1a` | Grades D–F; a failure-mode badge |
| `--unchecked` | `#6b645b` / `#ebe6dc` | `#9a9287` / `#23201b` | **Not checked.** Always dashed-bordered |

---

## 3. Typography

### Families

| Token | Stack | Used for |
|---|---|---|
| `--serif` | Iowan Old Style, Palatino Linotype, Palatino, Book Antiqua, Georgia, serif | All reading text: judgments, claims, findings, body |
| `--sans` | system UI stack | Apparatus only: labels, buttons, badges, hints, status |
| `--mono` | system mono stack | Verbatim input and output: the brief, the plan, reports |

**No web fonts.** Nothing is loaded from a third-party origin — the Content-Security-Policy is
`font-src 'self'`, and a font that would need `fonts.googleapis.com` cannot be added without weakening
it. Substitutes are chosen so the serif stack degrades to Georgia, which is on everything.

The serif/sans split carries meaning: **serif is what the court and the advocate wrote; sans is what
the tool says about it.** Never set a judgment's words in the sans stack.

### Scale

| Role | Size / leading | Family | Notes |
|---|---|---|---|
| Body | 16px / 1.55 | serif | |
| Masthead `h1` | 25px / 600 | serif | Wordmark in `--seal` with a 34×2px rule beneath |
| Strapline | 15px italic | serif | `--muted` |
| Card title `h2` | 11.5px / 700 | sans | Uppercase, `.11em` tracking, `--faint` |
| Judgment paragraph | 14.5px / 1.68 | serif | The longest read on the page |
| Claim / blockquote | 15.5–14.5px / 1.6 | serif | |
| Board row | 14px | serif | Seal / citation / findings grid |
| Hint, caption | 12.5px / 1.6 | sans | `--muted` |
| Badges | 11–11.5px | sans | |
| Code, textarea | 13px / 1.62, `pre` 12.5px | mono | |

---

## 4. Layout

**Spacing** is a 4px-derived but hand-tuned scale; the values in use are 2, 4, 6, 8, 10, 13, 14, 16,
22, 24, 26, 32, 44, 72.

| Region | Value |
|---|---|
| Page container | `max-width: 1240px`, padding `26px 32px 72px` |
| Masthead | padding `20px 32px 16px`, bottom `1px solid --rule-strong` |
| Card | padding `22px 24px`, `1px solid --rule`, radius 3px |
| Two-column row | `grid`, `5fr / 7fr`, gap 22px |
| Control cluster | `flex`, gap 10px, `margin-top: 13px` |

**Whitespace philosophy:** space goes into leading and margins, not into padding. A card is a sheet
with a hairline edge, not a floating panel — hence the near-flat shadow.

---

## 5. Elevation & Depth

Almost none, deliberately. One shadow token, used only on `.card`:

```
light  0 1px 2px rgba(26,23,20,.05), 0 8px 24px -12px rgba(26,23,20,.12)
dark   0 1px 2px rgba(0,0,0,.4),     0 8px 24px -12px rgba(0,0,0,.6)
```

Depth is carried by **hairline rules and left-borders**, not by layering. A 2px left border in a
semantic colour is the primary device for marking a passage: `--good` on a verified quotation,
`--bad` on a finding, `--warn` on a self-attack, `--seal` on the paragraph the engine read.

---

## 6. Shapes

`--radius: 3px` everywhere — cards, buttons, fields, badges' square variants. Pills (`999px`) are used
only for the status chip and for finding badges. Nothing is more rounded than 3px unless it is a pill.

The **grade seal** is the one bespoke shape: a 26px square-ish `inline-grid` with a 1px border, solid
for a decided grade and **dashed** when checks could not run.

---

## 7. Components

### Buttons
Primary is oxblood fill, `--paper-raised` text, 8×15px, sans 13.5px/550. `.quiet` is transparent with
an `--edge` border, which is the accessible one. Active nudges 1px down. Focus is a 2px `--seal` outline at 2px offset —
**never remove it.**

### Tabs
A row over a 1px rule; the active one is marked by a 2px `--seal` underline and 600 weight, never by a
fill. *A tab is a place you are, not a button you press* — and because `.tabs button` ties the generic
`button:hover` on specificity, the tab rules must restate `background: none`.

### Verdict board
**A list of `<button>`s, not a table of clickable rows.** The board is a set of citations you choose
between, which is what a button is; a `<tr onclick>` is unreachable by keyboard and needs a pile of
ARIA to pretend otherwise. Each button is a grid: seal, citation, findings. Hover tints to `--paper`,
selected adds `inset 3px 0 0 --seal` and `aria-pressed`, focus draws a 2px `--seal` ring inset.

Redrawing the board replaces the focused element, so the handler restores focus to the row it just
selected. The first verdict opens itself as it arrives — an empty panel beside a filling board is a
panel the reader has to be told about.

**Badges carry the finding's words, never its number.** "no such case", "pinpoint does not exist" —
the mode number belongs in a `title`, because `5` tells a reader nothing.

### Judgment viewer
Scrolling column of paragraphs, each with a sans label. The paragraph the engine actually read gets a
`--seal` left border and a 6% tint; the verified sentence inside it is `<mark>`ed. This is the point of
the whole viewer — nothing else on the page may compete with that marker.

### Empty states
Italic sans in `--faint`, one plain sentence. Never an illustration.

---

## 8. Do's and Don'ts

### Do
- Set anything a court or an advocate wrote in the serif.
- Reserve semantic colour for findings.
- Give *not checked* a dashed edge and a neutral tone.
- Keep the focus ring.
- Add a class to `app.css` instead of a `style=` attribute.
- Say what a finding is, in words.

### Don't
- **Never add inline `<script>`, `<style>`, `style=` or `on*=`.** The CSP is `script-src 'self'` with
  no `unsafe-inline`, and `tests/test_hardening.py` fails the build if any appears. This is a security
  boundary wearing a style rule's clothes.
- Never load a font, script or stylesheet from another origin.
- Never use green to mean "done" or red to mean "important".
- Never render *not checked* as a lighter failure.
- No gradients, no glassmorphism, no drop shadows beyond the one token, no icon set, no emoji in the
  interface, no animated progress.
- Never interpolate server text into markup without `escape()`.

---

## 9. Responsive Behavior

| Breakpoint | Behaviour |
|---|---|
| ≥ 941px | Two-column rows, 5fr / 7fr |
| ≤ 940px | Rows collapse to one column |
| ≤ 620px | Container padding drops to 18px; masthead 21px; strapline wraps to its own line |

The page must never scroll horizontally — asserted in the render check. Long content (tables, `pre`,
the paragraph column) scrolls inside its own container.

Touch targets: buttons are 34px tall at 13.5px text; keep ≥ 32px.

---

## 10. Iteration Guide

1. Read `src/orderorder/web/static/app.css` — the header comment carries the reasoning.
2. Change tokens, not literals. There should be no raw hex outside `:root` and its dark override.
3. Add both themes at once. A token defined only in light is a bug.
4. Run the suite: `uv run pytest tests/test_hardening.py`. It checks for inline script and style, for
   `on*=` handlers, that every class used is styled, and that every id the script reaches for exists.
5. Look at it. Two of the three bugs found in the last redesign — export buttons visible when they
   should have been hidden, and a tab filling on hover — were invisible in the source and obvious on
   screen.

---

## 11. Known Gaps

Five gaps were listed here when this file was written. All five are closed, and the entries are kept
because what was wrong is more useful than a clean list:

- ~~No keyboard access to the board~~ — it is a list of buttons now, verified focusable and operable
  in a real browser rather than assumed.
- ~~No reduced-motion query~~ — present, and it also stills the loading skeleton, which was the only
  thing left carrying a "still working" signal by motion alone.
- ~~Contrast unmeasured~~ — measured, and it failed. `--faint` was 3.36 against a card while carrying
  every card label and empty state; the quiet button's border was 1.83 while being the only thing that
  said it was a button. Both fixed, both now asserted in `tests/test_hardening.py` for both themes.
- ~~No print stylesheet~~ — present, and it drops the masthead, tabs, controls and the input card,
  which are furniture rather than document.
- ~~No skip link~~ — present, and verified to be the first thing the Tab key reaches.

What is still open:

- **No focus trap or `Escape` handling**, because there is no modal yet. The first one added will need
  both.
- **The judgment viewer scrolls inside a fixed height** rather than the page, so a very long judgment
  is a scroll within a scroll. Acceptable beside a board that must stay visible; worth revisiting.
- **Colour is doing real work in the grade seals**, and although the letter is always present as text,
  the mode badges are distinguished from *needs review* by colour and border style alone. A shape or
  glyph difference would be safer.
- **No automated axe/Lighthouse pass.** The checks in `test_hardening.py` are hand-written and cover
  what was actually wrong, which is not the same as coverage.
