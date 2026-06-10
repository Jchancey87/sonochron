---
name: improve-codebase-architecture
description: >
  Find deepening opportunities in the codebase, informed by agents_memory.md, ARCHITECTURE.md, and local schemas.
  Use when refactoring, consolidating modules, optimizing interfaces, or making the codebase more testable.
---

# Improve Codebase Architecture

Surface architectural friction and propose **deepening opportunities** — refactoring shallow modules (interface nearly as complex as implementation) into deep ones (rich functionality behind a clean, simple interface).

## Glossary & Concepts

Use these terms exactly when discussing or proposing architectural modifications:

- **Module** — any block of code with an interface and an implementation (e.g., helper functions, classes, API routes, database models).
- **Interface** — everything a caller must know to use the module: types, parameters, invariants, error handling behavior, ordering constraints.
- **Implementation** — the internal code.
- **Depth** — high leverage: a small interface hiding significant internal complexity.
- **Seam** — where an interface lives; a point where behavior can be swapped or modified without editing in place (e.g., using adapters).
- **Adapter** — a concrete class or function satisfying an interface at a seam.
- **Leverage** — the architectural benefit callers obtain from a deep module.
- **Locality** — concentrating logical change, bug fixes, and knowledge inside a single module rather than distributing it.

### Core Principles

1. **Deletion Test**: Imagine deleting the module. If complexity vanishes completely, it was a pass-through (shallow). If complexity reappears across N callers, the module was earning its keep.
2. **Interface is the Test Surface**: Tests should target the stable public interface, not implementation details.
3. **One Adapter = Hypothetical Seam. Two Adapters = Real Seam**: Avoid over-engineering interfaces for modules that will only ever have a single adapter, unless required for critical isolation boundaries.

## Architecture Review Report (HTML)

When proposing refactoring or architectural changes:
1. Write an interactive HTML report to the OS temporary directory (e.g., `/tmp/architecture-review-<timestamp>.html`).
2. Use **Tailwind CSS** (via CDN) for a premium, clean visual layout.
3. Use **Mermaid.js** (via CDN) or inline SVGs for side-by-side **Before/After** diagrams.
4. For each proposal, present a card details:
   - **Target Files**: Affected files and modules.
   - **Problem / Friction**: Why the current setup is causing cognitive load or testing complexity.
   - **Proposed Solution**: Plain explanation of how to consolidate/deepen the modules.
   - **Leverage & Locality Benefits**: How this enhances testability and simplifies callers.
   - **Recommendation Strength**: `Strong`, `Worth exploring`, or `Speculative`.
5. Tell the user the path to open the file in their browser. Do not implement the code changes until the user selects a candidate.
