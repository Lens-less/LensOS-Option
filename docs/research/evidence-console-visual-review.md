# Evidence Console Visual Review

Reviewed route: `/evidence`

Viewport coverage:

- desktop: `1440 × 1000`
- intermediate: `1024 × 800`
- compact navigation boundary: `600 × 844`
- mobile: `390 × 844`

## Functional contract

The page exists to answer, within three seconds:

1. Is the report service reachable and the contract validated?
2. Is the market evidence current and trustworthy?
3. Is the product releasable?
4. Which blockers require an operator, and which are system-owned?

The only operator action in this slice is refreshing or opening the raw
`research_report.v1`. The page contains no trading, sizing, order, or paper
candidate control.

## Design DNA

- IBM Carbon: 8 px spacing rhythm, square regions, cobalt `#0f62fe`, red
  `#da1e28`, green `#198038`, and tabular mono numerals.
- Vercel: ink `#171717`, one-pixel structural rules, compact six-pixel buttons,
  and a two-pixel blue focus treatment.
- Project anchor: warm white `#f7f7f5`, no gradients or glass, Chinese system
  typography, and `NO-GO` as the single dominant visual claim.

Signature craft details: custom selection color, visible keyboard focus,
hairline evidence grid, live evidence-age composition, split operator/system
queues, custom scrollbar, press feedback, and a quiet research-only footer.

## Round 1

Product:

- `NO-GO`, `RESEARCH_ONLY`, `NO_TRADE`, evidence availability, and both blocker
  owners were visible without scrolling on desktop.
- On mobile the same reading order collapsed correctly to verdict, freshness,
  operator actions, system actions, and evidence chain.

Visual:

- The editorial asymmetry and red/blue boundary system were coherent.
- Queue counts rendered as `03` and `04`, which could be mistaken for section
  numbering.

Craft:

- No gradients, glass, generic rounded cards, clipping, or horizontal overflow.
- The browser requested a missing favicon, producing one console 404.

UX/engineering:

- Desktop and mobile had no clipped elements.
- The mobile refresh target was only 40 px high.
- A portfolio evidence detail still exposed an English backend sentence.

## Round 2

Changes applied:

- queue counts now include the explicit `项` unit;
- an embedded SVG favicon removes the network error;
- the mobile refresh target is 44 px high;
- known status and portfolio evidence text is localized without altering raw
  reason codes.

Verification:

- desktop document width `1440`, viewport width `1440`;
- mobile document width `390`, viewport width `390`;
- zero horizontal overflow and zero detected visible clipping;
- zero browser console warnings or errors;
- refresh interaction returned to `aria-busy="false"`;
- the English portfolio sentence was absent.

## Round 3

Changes reviewed:

- the four-boundary truth strip now separates report availability, market
  evidence, product release, and the research-only execution boundary;
- explicit section numbers replace empty decorative markers;
- below 620 px, the page exposes a sticky, horizontally scrollable section
  rail with `aria-current`;
- unknown blocker ownership fails safe to manual triage, while healthy account
  and active-regime facts are excluded from blocker queues;
- Chinese UI copy uses 14 px or larger type without negative tracking, and the
  refresh target remains 44 px at every viewport.

Verification:

- at `1024 × 800`, the verdict/freshness hero remained two-column while the
  operator and system queues collapsed to one column;
- at `600 × 844`, verdict and queues were single-column, the truth strip was
  two-column, the section rail used `overflow-x: auto`, and every visible
  interactive target measured 44 px high;
- selecting `限制` changed `aria-current` to `location`, set the URL fragment
  to `#limitations`, and respected the 128 px anchor offset;
- at `390 × 844`, document width was 380 px inside a 390 px viewport with no
  horizontal overflow or visibly clipped element;
- the final packaged page produced zero page-origin console warnings or errors,
  and refresh returned to `aria-busy="false"`.
