# Copyright (c) 2026 Rafael
# OpenAI-compatible chat-completions client for the AI Slicing Assistant.
#
# Inside Cura, all network I/O goes through UM.TaskManagement.HttpRequestManager
# (non-blocking, integrated with Qt's event loop) -- never a blocking
# requests/urllib call, which would freeze Cura's UI thread.
#
# The __main__ block at the bottom is a standalone dev harness (plain
# urllib, no Cura/Qt needed) for iterating on the prompt/schema against a
# real endpoint without restarting Cura each time.

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

# This base prompt carries the non-negotiable safety rules (never propose
# out-of-bounds values, only whitelisted keys, etc). User-provided custom
# instructions (see build_system_prompt) are appended *after* this, framed
# as additional preferences, not a replacement -- ApplySettings.validate()
# enforces the bounds/whitelist regardless of what either prompt says, so
# this is defense in depth, not the only safety layer.
BASE_SYSTEM_PROMPT = """You are a 3D-printing slicing assistant embedded in UltiMaker Cura.

You will be shown several photos of a 3D model currently loaded in the slicer \
(taken from different corner angles plus a top-down view), a description of \
the user's intent for this specific print, and a JSON list of the print \
settings you're allowed to adjust -- each with its current value, unit, \
allowed min/max, and a short description.

Your job: propose a small set of setting changes that best match the user's \
stated intent (for example: a quick fit-check should minimize print time and \
material use as long as dimensional accuracy isn't compromised; a real \
structural/functional part should prioritize strength -- more walls, denser \
or solid infill, slower speed for better layer bonding -- even at the cost \
of time and material).

Rules:
- Only propose changes to settings that appear in the provided settings list. \
Do not invent setting keys.
- Never propose a numeric value outside the given minimum_value/maximum_value \
for that setting -- those are hard machine/material limits, not suggestions.
- If a setting is already appropriate for the stated intent, leave it out of \
your response rather than restating the current value.
- Keep "reasoning" to one short sentence per change, in plain language a \
non-expert can understand.
- Base your visual judgement (overhangs, thin walls, expected load paths) on \
the photos provided.
- IMPORTANT: "value" must always be a JSON string, even for numbers and \
booleans -- e.g. "50", "0.2", "true", "gyroid". Do not send a raw number or \
boolean for "value".
"""


def build_system_prompt(custom_instructions: str = "") -> str:
    """Combine the fixed safety-rule prompt with the user's own optional
    preferences (e.g. "always prefer gyroid infill", "assume PETG unless
    told otherwise"). The custom part is clearly separated and framed as
    *additional* guidance -- it cannot remove the base rules from the
    prompt, and even if a user's wording tried to, ApplySettings.validate()
    still enforces the real bounds/whitelist independently.
    """
    if not custom_instructions.strip():
        return BASE_SYSTEM_PROMPT
    return (
        BASE_SYSTEM_PROMPT
        + "\nAdditional user preferences (follow these as long as they don't "
        "conflict with the rules above):\n"
        + custom_instructions.strip()
        + "\n"
    )

# NOTE: "value" is deliberately typed as a plain string here, not a
# union/array type (e.g. NOT {"type": ["number", "string", "boolean"]}).
# Some OpenAI-compatible providers (confirmed: MiniMax) reject union types in
# response_format json_schema with a 400 before ever generating a response.
# A single "string" type is the lowest common denominator that works across
# providers; SettingChange values arrive as strings and are coerced to the
# right type in ApplySettings.validate() based on the setting's real type.
RESPONSE_SCHEMA: Dict[str, Any] = {
    "name": "print_settings_suggestion",
    "schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["key", "value", "reasoning"],
                },
            },
        },
        "required": ["summary", "changes"],
    },
}


@dataclass
class SettingChange:
    key: str
    proposed_value: Any
    reasoning: str


@dataclass
class AIResponse:
    summary: str
    changes: List[SettingChange]
    raw_error: Optional[str] = None


def build_request(intent_text: str, images_b64: List[str], settings_context: List[Dict[str, Any]],
                   model: str, custom_instructions: str = "") -> Dict[str, Any]:
    """Build the OpenAI-compatible /v1/chat/completions request body."""
    content: List[Dict[str, Any]] = [
        {"type": "text", "text": "User's stated intent for this print:\n" + intent_text},
        {"type": "text", "text": "Adjustable settings (current value, unit, bounds, description):\n" + json.dumps(settings_context, indent=2)},
    ]
    for image_b64 in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + image_b64},
        })

    return {
        "model": model,
        "messages": [
            {"role": "system", "content": build_system_prompt(custom_instructions)},
            {"role": "user", "content": content},
        ],
        "response_format": {"type": "json_schema", "json_schema": RESPONSE_SCHEMA},
        "temperature": 0.2,
    }


def _extract_json_payload(text: str) -> Optional[Any]:
    """Pull a JSON value out of free-form model output.

    Several OpenAI-compatible "reasoning" models (confirmed: MiniMax-M3;
    also known to affect DeepSeek-R1/Qwen-style models) ignore
    response_format constraints and instead: prepend a <think>...</think>
    reasoning block, then wrap the actual JSON in a ```json ... ``` markdown
    fence. This strips both before parsing, then falls back to bracket
    matching if the result still isn't clean JSON.
    """
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

    fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Last resort: find the outermost {...} or [...] block by bracket search.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = cleaned.find(open_ch)
        end = cleaned.rfind(close_ch)
        if start == -1 or end == -1 or end <= start:
            continue
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            continue

    return None


def parse_response(body: Optional[Dict[str, Any]]) -> AIResponse:
    """Defensively parse a chat-completions response body into an AIResponse.

    Never raises. Some OpenAI-compatible endpoints don't honor
    response_format strictly (some ignore it and return a completely
    different JSON shape, e.g. a bare array instead of {"summary",
    "changes"}), so this does not assume the shape is guaranteed just
    because it was requested -- both shapes are accepted.
    """
    if not isinstance(body, dict):
        return AIResponse(summary="", changes=[], raw_error="Empty or invalid response body")

    try:
        message_content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return AIResponse(summary="", changes=[], raw_error="Response did not contain choices[0].message.content")

    if isinstance(message_content, str):
        parsed = _extract_json_payload(message_content)
        if parsed is None:
            return AIResponse(summary="", changes=[], raw_error="message.content was not valid JSON")
    else:
        parsed = message_content

    # Accept either {"summary": ..., "changes": [...]} or a bare list of
    # change objects (some models ignore the wrapper object entirely).
    if isinstance(parsed, list):
        summary = ""
        raw_changes = parsed
    elif isinstance(parsed, dict):
        summary = parsed.get("summary", "")
        if not isinstance(summary, str):
            summary = ""
        raw_changes = parsed.get("changes", parsed.get("suggestions", []))
    else:
        return AIResponse(summary="", changes=[], raw_error="Parsed content was neither a JSON object nor array")

    if not isinstance(raw_changes, list):
        raw_changes = []

    changes: List[SettingChange] = []
    for entry in raw_changes:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        reasoning = entry.get("reasoning", "")
        if not isinstance(key, str) or "value" not in entry:
            continue
        changes.append(SettingChange(
            key=key,
            proposed_value=entry["value"],
            reasoning=reasoning if isinstance(reasoning, str) else "",
        ))

    return AIResponse(summary=summary, changes=changes)


def send_request_async(base_url: str, api_key: str, model: str, intent_text: str,
                        images_b64: List[str], settings_context: List[Dict[str, Any]],
                        on_success: Callable[[AIResponse], None],
                        on_error: Callable[[str], None],
                        custom_instructions: str = "") -> None:
    """Send the request from inside Cura via HttpRequestManager -- non
    blocking, callback-driven, integrated with Qt's event loop."""
    from UM.TaskManagement.HttpRequestManager import HttpRequestManager

    url = base_url.rstrip("/") + "/chat/completions"
    request_body = build_request(intent_text, images_b64, settings_context, model, custom_instructions)
    data = json.dumps(request_body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + api_key,
    }

    def _callback(reply):
        body = HttpRequestManager.readJSON(reply)
        on_success(parse_response(body))

    def _error_callback(reply, error):
        on_error(HttpRequestManager.qt_network_error_name(error))

    HttpRequestManager.getInstance().post(
        url,
        headers_dict=headers,
        data=data,
        callback=_callback,
        error_callback=_error_callback,
        timeout=60,
    )


if __name__ == "__main__":
    # Standalone dev harness -- iterate on the prompt/schema against a real
    # OpenAI-compatible endpoint without needing Cura running at all.
    # Usage: python3 AIClient.py <base_url> <api_key> <model> <intent text>
    import sys
    import urllib.request

    if len(sys.argv) < 5:
        print("Usage: python3 AIClient.py <base_url> <api_key> <model> <intent text>")
        sys.exit(1)

    dev_base_url, dev_api_key, dev_model, dev_intent = sys.argv[1], sys.argv[2], sys.argv[3], " ".join(sys.argv[4:])

    # Canned settings context standing in for SettingsSchema.get_all_bounds()
    # output, so this harness doesn't need a running Cura instance.
    dev_settings_context = [
        {"key": "infill_sparse_density", "label": "Infill Density", "type": "float", "unit": "%",
         "current_value": 15, "minimum_value": 0, "maximum_value": 100,
         "description": "How dense the internal fill is."},
        {"key": "wall_line_count", "label": "Wall Line Count", "type": "int", "unit": "",
         "current_value": 3, "minimum_value": 1, "maximum_value": 10,
         "description": "Number of walls/perimeters."},
        {"key": "support_enable", "label": "Generate Supports", "type": "bool", "unit": "",
         "current_value": False, "minimum_value": None, "maximum_value": None,
         "description": "Whether to generate support structures."},
    ]

    dev_request = build_request(dev_intent, [], dev_settings_context, dev_model)
    dev_req = urllib.request.Request(
        dev_base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(dev_request).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + dev_api_key},
        method="POST",
    )
    with urllib.request.urlopen(dev_req, timeout=60) as resp:
        dev_body = json.loads(resp.read().decode("utf-8"))

    dev_result = parse_response(dev_body)
    print("Summary:", dev_result.summary)
    for dev_change in dev_result.changes:
        print(f"  {dev_change.key} -> {dev_change.proposed_value}  ({dev_change.reasoning})")
    if dev_result.raw_error:
        print("Parse error:", dev_result.raw_error)
        print("Raw body:", json.dumps(dev_body, indent=2))
