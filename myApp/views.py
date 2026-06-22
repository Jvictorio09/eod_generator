import json
import os
from pathlib import Path
from urllib import error, request

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def home(request):
    return render(request, "index.html")


@csrf_exempt
@require_POST
def generate_eod_report(request):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return JsonResponse(
            {"error": "OPENAI_API_KEY is missing in .env"},
            status=500,
        )

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    resolved = payload.get("tasks", {})
    name = payload.get("name") or "Team member"
    date_str = payload.get("date") or "Today"
    style = (payload.get("style") or "").strip()
    model = (payload.get("model") or "gpt-4o-mini").strip() or "gpt-4o-mini"

    system_prompt = """You are a concise, professional end-of-day report writer. Turn raw task bullets into a clean EOD report using EXACTLY this structure and tone:

EOD REPORT — <n> - <DATE>

1. TASKS COMPLETED
<If tasks have a "project" tag, group them under that project as a sub-header on its own line (no bullet, just the project name). Then list the bullets under it. If there are no project tags, list flat bullets. Each bullet starts with "- ". Rewrite the user's shorthand into clear, professional, full-sentence language — expand acronyms where possible, add natural context, make it read like a status update to a team, not a personal to-do. You MAY use sub-headers like "Fixes", "Planning", or "Shipped" under a project ONLY if the content clearly calls for that organization; otherwise just list bullets.>

2. IN PROGRESS
- <bullet (rewritten professionally)>

3. BLOCKERS / RISKS
- <bullet — use formats like "Waiting on: …", "Risk: …", or "Blocked by: …" depending on nature of the blocker. Combine related blockers into a single fluid sentence when it reads better.>

4. TOMORROW'S PRIORITIES
- <bullet>

RULES:
- Keep the exact section headers and numbering ("1. TASKS COMPLETED", etc., all caps).
- If a section has no items, write "- None." under it.
- Do NOT invent tasks that weren't provided.
- Each bullet must be a complete, professional sentence. Rewrite shorthand like "work on website 1" into a real status line. If there's truly no context to infer, phrase it cleanly and generically ("Continued progress on Website 1.").
- Do NOT use markdown bold (**), do NOT use emojis, do NOT add preamble or closing remarks.
- Output plain text only, ready to paste into Slack or email."""

    user_prompt = f"""Generate the EOD report.

NAME: {name}
DATE: {date_str}

TASKS (resolved into sections, JSON):
{json.dumps(resolved, indent=2)}

{f"ADDITIONAL STYLE GUIDANCE FROM USER:\\n{style}" if style else ""}"""

    openai_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.4,
    }

    req = request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(openai_payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(raw)
            msg = parsed.get("error", {}).get("message") or f"HTTP {exc.code}"
        except json.JSONDecodeError:
            msg = f"HTTP {exc.code}"
        return JsonResponse({"error": msg}, status=exc.code)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=500)

    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )
    if not content:
        return JsonResponse({"error": "Empty response from OpenAI"}, status=502)

    return JsonResponse({"report": content})