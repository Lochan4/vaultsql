Before making any changes to the frontend, you MUST:

1. Read `docs/frontend-design.md` in full
2. Confirm the proposed change does not violate any principle in that file
3. If it does, state which principle it violates and propose an alternative that complies

Then implement the following frontend task: $ARGUMENTS

During implementation, enforce these non-negotiables:
- All colors via CSS tokens from `src/styles/tokens.css` — no hardcoded hex
- Two fonts only: Inter (UI) and JetBrains Mono (SQL/code/data)
- Dark theme only — no light backgrounds except the DBConnector onboarding card
- No gradients, no drop shadows, no glassmorphism
- Every interactive element must have default / hover / active / disabled / focus states
- SQL blocks use JetBrains Mono 13px with copy button
- Result tables: JetBrains Mono for cells, numeric columns right-aligned
- Chart output is a backend-rendered PNG — display as `<img>`, do not recreate in JS
- Motion: fade-in only (200ms), no bounce, no spring

After implementing, do a self-check:
- Do all new components use only token values for color?
- Are all four interaction states covered?
- Does the layout match the sidebar + main area structure from the design doc?
- Is there any hardcoded color, gradient, or shadow that shouldn't be there?

If any check fails, fix it before finishing.
