# Frontend transformation audit and implementation checklist

Existing stack: Next.js 16.4.5 App Router, React 19.3.1, TypeScript, custom SVG icons and native dialogs. Routes: chat, library, vaults, graph, settings, diagnostics. Auth uses server cookie + CSRF through the typed HTTP client; original backend contracts remain unchanged. The backend returns complete verified answers, not token streams.

Problems: 2,200+ accumulated CSS lines, light-only hardcoded colors, fixed broad sidebar/header, frequent idle polling, plain-text message formatting, little shared motion, no document grid/drop feedback, graph selection colors computed inline, large components loaded on every route and no list windowing.

Design: dark charcoal, readable neutral typography, restrained periwinkle accent, compact floating icon rail with item expansion/focus and pinned mode, optional conversations pane, contextual content controls, layered home only, generous reading surfaces. Light mode remains an optional user preference.

- [x] Record baseline type/lint/build and three no-key browser regressions; isolate test storage.
- [x] Shared tokens, lazy Motion/native reduced-motion primitives, persistent auth/theme preferences.
- [x] Icon rail, physical hover/focus label expansion, mobile drawer, one-entry brand reveal and page continuity.
- [x] Chat Markdown/GFM/math, code copy, verified citation buttons, scroll intent, honest stop-waiting state and composer model shortcut.
- [x] Real document grid/list, drag/drop/progress, bounded DOM lists, vault/graph selection and source previews.
- [x] Settings tabs/advanced panels, diagnostics and login styling, keyboard/touch/accessibility pass.
- [x] Type/lint/build, original + new responsive/motion/security/browser scenarios, asset/request/performance measurements, report.

Use existing APIs, lightweight lazy Motion for React and native CSS/View Transitions where supported, with instant/reduced-motion fallbacks. No new backend feature, fake streaming, fake statistics, remote image loads or secret fields. Reuse existing icons. Markdown/math dependencies are pinned and deferred until messages are rendered. Public source/data/auth boundaries stay intact. Final results and limitations: `FRONTEND_TRANSFORMATION_REPORT.md`.
