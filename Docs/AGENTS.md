# Agent Notes

## Planning Before Implementation

- Do not write implementation code before the user explicitly asks to start coding.
- Before coding starts, only create or update planning Markdown files.
- If exploratory code is accidentally created early, move it into `archive/` as reference material and keep it out of the active project root.

## Code Design Preference

- Prefer the smallest practical implementation.
- Keep methods single-purpose.
- Use interface-style boundaries for replaceable data sources, especially CSV/API acquisition for Atera and Bitdefender.
- Keep comparison logic independent from how CSV data is obtained.
