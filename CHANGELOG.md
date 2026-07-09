# Changelog

## 0.2.0 — Configurability

- Multiple named API profiles (endpoint/model/key), switchable from a dedicated tab.
- Whitelist editor: choose exactly which print settings the AI can see/suggest, grouped by category, instead of a fixed hardcoded list.
- Optional custom instructions appended to the assistant's system prompt (e.g. "always prefer gyroid infill").
- Dialog reorganized into three tabs: Assistant, API Profiles, Advanced.

## 0.1.0 — Initial release

- Capture 4-corner + top-down photos of the loaded model.
- Send photos, stated intent, and a whitelisted settings context to any OpenAI-compatible chat completions endpoint.
- Review table of suggested changes with live clamping/rejection against the machine and material's real limits before anything is applied.
- API key stored via OS keyring when available, falling back to a permission-restricted local file.
- Apply approved suggestions to the active print profile; slicing itself stays a manual step via Cura's own Slice button.
