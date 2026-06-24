import json
from urllib import error, request

from django.conf import settings


class AIError(Exception):
    pass


def _api_key():
    key = getattr(settings, "OPENAI_API_KEY", "") or ""
    key = key.strip()
    if not key:
        raise AIError(
            "OPENAI_API_KEY is missing. Add it to your .env file and restart the server."
        )
    if not key.startswith("sk-"):
        raise AIError(
            "OPENAI_API_KEY looks invalid (should start with sk-). Check your .env file."
        )
    return key


def chat_completion(*, model, messages, temperature=0.4, timeout=60):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    req = request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_api_key()}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(raw)
            msg = parsed.get("error", {}).get("message") or f"HTTP {exc.code}"
        except json.JSONDecodeError:
            msg = f"HTTP {exc.code}"
        if exc.code == 401 or "incorrect api key" in msg.lower():
            msg = (
                "OpenAI rejected your API key. Create a new key at "
                "https://platform.openai.com/api-keys, update .env, then restart runserver."
            )
        raise AIError(msg) from exc
    except Exception as exc:
        raise AIError(str(exc)) from exc

    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )
    if not content:
        raise AIError("Empty response from OpenAI")
    return content


_FORMAT_INSTRUCTIONS = {
    "PLAIN": (
        "Output plain text only, ready to paste anywhere. "
        "Use EXACTLY this structure:\n\n"
        "EOD REPORT — <name> - <DATE>\n\n"
        "1. TASKS COMPLETED\n"
        "2. IN PROGRESS\n"
        "3. BLOCKERS / RISKS\n"
        "4. TOMORROW'S PRIORITIES\n"
        "Each bullet starts with '- '. If a section is empty, write '- None.'"
    ),
    "SLACK": (
        "Format for a Slack channel post. Start with a one-line summary, then use "
        "emoji section headers (e.g. :white_check_mark: *Completed*, :construction: *In progress*). "
        "Keep bullets short. Slack mrkdwn is OK (*bold* sparingly). No email greeting."
    ),
    "EMAIL": (
        "Format as a manager email. Include:\n"
        "Subject: EOD Update — <name> — <DATE>\n\n"
        "Hi team,\n\n"
        "<body with clear sections>\n\n"
        "Best,\n<name>"
    ),
}

_TONE_INSTRUCTIONS = {
    "professional": "Tone: professional, clear, team-update style.",
    "casual": "Tone: warm and conversational, still work-appropriate.",
    "concise": "Tone: ultra-concise — shortest possible phrasing, no filler.",
}

_LENGTH_INSTRUCTIONS = {
    "brief": "Length: brief — max 1 bullet per section where possible.",
    "standard": "Length: standard — one clear sentence per bullet.",
    "detailed": "Length: detailed — add helpful context to each bullet.",
}


def generate_eod_report(
    *,
    name,
    date_str,
    tasks_payload,
    style="",
    model="gpt-4o-mini",
    report_format="PLAIN",
    tone="professional",
    length="standard",
):
    fmt = report_format if report_format in _FORMAT_INSTRUCTIONS else "PLAIN"
    tone_key = tone if tone in _TONE_INSTRUCTIONS else "professional"
    len_key = length if length in _LENGTH_INSTRUCTIONS else "standard"

    system_prompt = f"""You are an end-of-day report writer.

{_FORMAT_INSTRUCTIONS[fmt]}
{_TONE_INSTRUCTIONS[tone_key]}
{_LENGTH_INSTRUCTIONS[len_key]}

RULES:
- Do NOT invent tasks that weren't provided.
- Rewrite shorthand into clear language.
- Do NOT add preamble beyond what the format requires."""

    style_guidance = (
        f"ADDITIONAL STYLE GUIDANCE FROM USER:\n{style}" if style else ""
    )
    user_prompt = f"""Generate the EOD report.

NAME: {name}
DATE: {date_str}
FORMAT: {fmt}

TASKS (resolved into sections, JSON):
{json.dumps(tasks_payload, indent=2)}

{style_guidance}"""

    return chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
    )


def parse_braindump(text, *, model="gpt-4o-mini"):
    system_prompt = """Parse a messy end-of-day brain dump into structured tasks.
Return ONLY valid JSON — an array of objects with keys:
- "title" (string, concise task description)
- "status" (one of: "DONE", "IN_PROGRESS", "BLOCKED", "TOMORROW")

Infer status from context. Default to IN_PROGRESS when unclear.
Do not invent tasks not mentioned. No markdown, no explanation."""

    content = chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        temperature=0.3,
    )
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AIError("Could not parse brain dump response") from exc
    if not isinstance(parsed, list):
        raise AIError("Brain dump response must be a JSON array")
    return parsed


def generate_manager_digest(summary_payload, *, model="gpt-4o-mini"):
    system_prompt = """Write a brief, actionable manager digest (3-5 sentences) for an end-of-day team standup.
Tone: supportive, not surveillance. Focus on what shipped, what's stuck, and where the manager can unblock.
No bullet points. Plain text only."""

    return chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(summary_payload, indent=2)},
        ],
        temperature=0.5,
    )


_OVERSIGHT_ASSISTANT_RULES = """You are CloseOut's oversight assistant for managers and executives.
You help them understand team end-of-day (EOD) status without clicking through the dashboard.

RULES:
- Only use facts from the CONTEXT JSON. Never invent names, tasks, or blockers.
- Respect date_context in CONTEXT: on future dates nobody is "pending"; on past dates say "not posted"; only today uses "pending".
- Tone: professional, supportive — helpful colleague, not surveillance.
- Be concise and scannable. Short paragraphs or light bullets (-) are fine.
- If data is missing, say what you can see and what isn't available yet.
- Do not use markdown headers (#). Plain text only."""


def generate_oversight_summary(*, snapshot, model="gpt-4o-mini", viewer_name=""):
    greeting = f"Hi {viewer_name}," if viewer_name else "Hi,"
    date_ctx = snapshot.get("date_context") or {}
    date_note = date_ctx.get("guidance", "")
    system_prompt = f"""{_OVERSIGHT_ASSISTANT_RULES}

The user is viewing oversight data. Write an opening summary for them.
DATE CONTEXT: {date_note}

Structure your reply roughly as:
1. One-line snapshot of posting compliance for the scope they're viewing (use correct pending / not-posted / not-due language per date_context)
2. Highlights — what shipped or progressed (if visible in data)
3. Blockers or risks that need attention (if any)
4. Who still needs to post — only if date_context.is_today or date_context.is_past; never call future dates "pending"
5. End with this exact closing on its own paragraph:
"If you have questions or want to dig deeper, feel free to ask here — I'm here to help."

Start with "{greeting}" then the summary. Keep it under 220 words unless blockers require more detail."""

    return chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"CONTEXT:\n{json.dumps(snapshot, indent=2)}",
            },
        ],
        temperature=0.45,
        timeout=90,
    )


def oversight_assistant_chat(*, snapshot, messages, model="gpt-4o-mini", viewer_name=""):
    system_prompt = f"""{_OVERSIGHT_ASSISTANT_RULES}

The manager may ask follow-up questions about the team data below.
Answer clearly and briefly. Suggest concrete follow-ups (who to ping, what to unblock) when appropriate.
If the answer isn't in the data, say so honestly.

CONTEXT:
{json.dumps(snapshot, indent=2)}"""

    chat_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            chat_messages.append({"role": role, "content": content})

    return chat_completion(
        model=model,
        messages=chat_messages,
        temperature=0.4,
        timeout=90,
    )


def generate_week_review(*, name, week_payload, model="gpt-4o-mini"):
    system_prompt = """Write a personal "week in review" for 1:1 prep.
Structure:
- Highlights (what shipped)
- Themes (patterns across the week)
- Open threads (still in progress or blocked)
- Suggested talking points for manager 1:1

Tone: first-person, reflective, supportive. Plain text. 200-350 words max."""

    return chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"NAME: {name}\n\nDATA:\n{json.dumps(week_payload, indent=2)}"},
        ],
        temperature=0.5,
    )
