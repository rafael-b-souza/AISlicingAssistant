# AI Slicing Assistant

Get print-setting suggestions for the model you have loaded, based on photos of it and a plain-language description of what the part is for — reviewed and applied inside Cura, never applied automatically.

## What it does

The dialog has three tabs:

- **Assistant** — the main flow. You load a model, type what the print is for (e.g. *"just a fit-check, don't worry about strength"* or *"real structural part, needs to hold load"*), click **Capture model & ask AI**, and get back a table of suggested setting changes with reasoning for each. Nothing is applied until you check the boxes you want and click **Apply selected** — slicing itself stays a manual step via Cura's own Slice button.
- **API Profiles** — save multiple named endpoint configs (e.g. "GPT-4o", "MiniMax", "Local Ollama") and pick which one is active. Each profile has its own name, base URL, model, and API key.
- **Advanced** — choose exactly which print settings the AI is allowed to see/suggest changes for (grouped checklist, not all-or-nothing), and add optional custom instructions appended to the assistant's system prompt (e.g. *"always prefer gyroid infill"*).

Under the hood: the plugin renders 5 photos of the model (4 corners + top-down) and sends them, together with your intent, your custom instructions (if any), and the current value/unit/allowed min-max of every setting you've enabled in the whitelist, to the active profile's endpoint.

## Data sent to a third party — read this before using

This plugin's entire purpose is to send data to an AI API, **so it does**: the 5 rendered photos of your model, your typed intent, any custom instructions you've added, and the names/current values of the settings you've enabled in the whitelist.

- This only happens when you click **"Capture model & ask AI"** — never automatically, never in the background.
- It's sent to **whatever endpoint the active profile points to**. The plugin ships with no default third-party service and does not phone home to anything of its own — you point each profile at OpenAI, a self-hosted/local server, or any other OpenAI-compatible endpoint.
- Each profile's API key is stored using your OS keyring if available, and otherwise a local file only readable by your own user account (`ai_slicing_assistant_apikey_<profile>` in Cura's data directory, `chmod 600`). It is never transmitted anywhere except as the `Authorization` header of the request to that profile's own configured endpoint.
- No print settings are ever changed without you explicitly reviewing and approving them in the table first — see Safety below.

## Requirements

- Cura 5.x
- An API key for at least one OpenAI-compatible chat completions endpoint (`/v1/chat/completions`) with vision (image input) support, e.g. a model that can read images.

## Safety

Every suggested change is checked against the *live* minimum/maximum values Cura's own settings system reports for your specific machine and material before it's ever shown to you:

- Numeric suggestions outside the real allowed range are **clamped**, not applied as-is.
- Suggestions for settings outside your currently-enabled whitelist (Advanced tab) are **rejected** — disabling a setting there genuinely prevents the AI from changing it.
- Invalid enum values (e.g. an adhesion type that doesn't exist) are **rejected**.
- Rejected/clamped rows are shown with the reason, but only genuinely valid suggestions are checked by default.
- Custom instructions (Advanced tab) are appended as *additional* preferences, not a replacement for these rules — even if worded to try to override them, the clamping/rejection above still applies independently.

## Known limitations (v1)

- Single active extruder only.
- One suggestion request per click — no multi-turn follow-up conversation yet.
- Does not trigger slicing itself; use Cura's own Slice button after applying.
