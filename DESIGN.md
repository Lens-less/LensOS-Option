# Crypto Options Research Console Design Anchor

## 1. Visual Theme And Atmosphere

This project uses an institutional research-console style: calm, dense, and evidence-led. The page should feel like a risk desk screen, not a marketing landing page. The strongest first impression must be that the system is research-only, gated, and auditable.

Design read: financial research and risk dashboard, for options researchers and risk operators, using restrained trust language, leaning on financial precision plus developer-tool discipline.

Dial settings:
- Variance: 4/10. Financial trust beats novelty.
- Motion: 2/10. Frequent-use controls need crisp feedback only.
- Density: 7/10. The user should compare evidence, risk, readiness, and blockers in one scan.

## 2. Color Palette And Roles

- Canvas: warm off-white, never pure white as the whole experience.
- Sidebar: charcoal, not pure black.
- Panels: white to warm-gray surfaces with hairline borders.
- Success: muted green for validated/pass states.
- Warning: amber for review/no-new-trades states.
- Error: muted red for halt/missing/blocked states.
- Information: blue-green/cyan for research-only neutral states.

Use accent colors only for status and interaction. Do not add decorative purple-blue gradients, neon glows, or large color clouds.

## 3. Typography Rules

Use a system UI stack with Chinese fallbacks for local robustness. Numbers and technical identifiers should use tabular numerals or a monospace stack. Avoid italics, decorative web fonts, gradient text, and oversized hero typography. Hierarchy comes from weight, spacing, and information placement.

## 4. Component Style

- Radius: 8px for cards and panels, 6px for compact controls, pills only for badges/chips.
- Borders: hairline dividers and low-contrast rails are preferred over heavy shadows.
- Cards are valid here because the page is a framed operational tool; avoid nested decorative card layers.
- Icon buttons need visible focus and active states.
- Status pills must not wrap into broken syllables.

## 5. Layout Principles

The first viewport should show the command strip, reason tape, and top of the evidence/risk/readiness workbench. The left rail anchors navigation. At mobile widths, collapse to a single column while preserving the command strip before secondary panels.

Functional contract:
- The page exists to show evidence chain, risk state, readiness, and no-trade blockers quickly.
- In three seconds, the user must know action, risk state, readiness, and why the system cannot trade.
- The page must not expose trade, order, sizing, or manual candidate controls.

## 6. Depth And Elevation

Depth is built through luminance steps, borders, and tiny tinted shadows. Borrowed DNA:
- From Kraken: muted crypto-finance semantic colors, 8-12px functional radius, whisper shadows.
- From Linear: dark native sidebar, semi-transparent borders, 6-8px tool controls, luminance-based surface hierarchy.

## 7. Do's And Don'ts

Do keep status language concrete and contract-bound. Do make focus, hover, active, loading, error, and empty states visible. Do keep route/debug information secondary.

Do not show persistent "loading/loaded" status as normal UI. Do not use fake trading affordances. Do not add Qiaomu profile links, decorative social strips, or unrelated branding.

## 8. Responsive Behavior

At widths below 900px, the sidebar becomes a compact top rail and the workbench becomes one column. At widths below 620px, command cards, matrix cells, and split stats stack, while tables remain horizontally scrollable inside their own regions.

## 9. Motion Philosophy

Motion is functional and short. Use explicit property transitions, custom ease-out, hover only under pointer-capable media queries, and `prefers-reduced-motion` support. Frequent controls should feel responsive within 160ms.
