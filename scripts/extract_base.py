"""Extract base.html and refactor index.html to extend it."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
index_path = ROOT / "myApp/templates/index.html"
text = index_path.read_text(encoding="utf-8")

style_start = text.index("<style>") + len("<style>")
style_end = text.index("</style>")
styles = text[style_start:style_end].strip()

body_start = text.index("<body>") + len("<body>")
script_start = text.rindex("<script>")
body_content = text[body_start:script_start].strip()
app_script = text[script_start + len("<script>") : text.rindex("</script>")].strip()

base = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{{% block title %}}CloseOut{{% endblock %}}</title>
<script>
  (function () {{
    var k = 'closeout:theme';
    var t = localStorage.getItem(k);
    if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
    else document.documentElement.setAttribute('data-theme',
      window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  }})();
</script>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='8' fill='%2309090B'/><rect x='8' y='14' width='16' height='2' rx='1' fill='white'/><rect x='8' y='18' width='10' height='2' rx='1' fill='%2371717A'/></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
{styles}

  /* ── Shared layout (dashboard, login) ── */
  .page {{ max-width: 1100px; margin: 0 auto; padding: 32px 24px 80px; }}
  .page h1 {{ font-size: 28px; font-weight: 700; letter-spacing: -0.03em; margin-bottom: 8px; }}
  .page .sub {{ color: var(--text-3); margin-bottom: 24px; font-size: 13px; }}
  .breadcrumb {{ display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-3); margin-bottom: 20px; flex-wrap: wrap; }}
  .breadcrumb a {{ color: var(--text-2); text-decoration: none; }}
  .breadcrumb a:hover {{ color: var(--text); }}
  .date-picker {{ margin-bottom: 20px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .date-picker label {{ font-size: 13px; color: var(--text-2); }}
  .date-picker input {{
    padding: 8px 12px; border-radius: 10px; border: 1px solid var(--border);
    background: var(--surface); color: var(--text); font-family: var(--font); font-size: 13px;
  }}
  .board-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .board-card {{
    display: block; padding: 18px 20px; border-radius: var(--radius-lg); border: 1px solid var(--border);
    background: var(--surface); text-decoration: none; color: inherit; transition: all var(--ease);
  }}
  .board-card:hover {{ border-color: var(--border-hover); background: var(--surface-hover); }}
  .board-card h3 {{ font-size: 15px; font-weight: 600; margin-bottom: 8px; }}
  .board-card p {{ font-size: 12px; color: var(--text-3); }}
  .people-list {{ display: flex; flex-direction: column; gap: 8px; }}
  .people-row {{
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    padding: 14px 16px; border-radius: var(--radius); border: 1px solid var(--border);
    background: var(--surface); text-decoration: none; color: inherit; transition: all var(--ease);
  }}
  .people-row:hover {{ border-color: var(--border-hover); background: var(--surface-hover); }}
  .people-row .name {{ font-weight: 600; font-size: 14px; }}
  .people-row .meta {{ font-size: 12px; color: var(--text-3); margin-top: 2px; }}
  .role-badge {{
    font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
    padding: 3px 8px; border-radius: 999px; background: var(--accent-dim); color: var(--text-2);
  }}
  .role-badge.manager {{ background: var(--violet-dim); color: var(--violet); }}
  .status-pill {{
    font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 999px; white-space: nowrap;
  }}
  .status-pill.posted {{ background: var(--green-dim); color: var(--green); }}
  .status-pill.pending {{ background: var(--amber-dim); color: var(--amber); }}
  .eod-content {{
    white-space: pre-wrap; font-size: 14px; line-height: 1.65; color: var(--text-2);
    padding: 16px; border-radius: var(--radius); background: var(--bg-elevated); border: 1px solid var(--border);
  }}
  .task-list-simple {{ list-style: none; }}
  .task-list-simple li {{
    padding: 10px 0; border-bottom: 1px solid var(--border); font-size: 13px;
  }}
  .task-list-simple li:last-child {{ border-bottom: none; }}
  .task-chip-inline {{ font-size: 11px; color: var(--amber); margin-top: 4px; }}
  details.task-collapse summary {{
    cursor: pointer; font-size: 13px; font-weight: 600; color: var(--text-2); padding: 8px 0;
  }}
  .empty-state {{ padding: 32px; text-align: center; color: var(--text-3); font-size: 13px; }}
  .login-wrap {{
    min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px;
  }}
  .login-card {{
    width: 100%; max-width: 400px; background: var(--surface); border: 1px solid var(--border);
    border-radius: 16px; padding: 32px;
  }}
  .login-card h1 {{ font-size: 22px; font-weight: 700; letter-spacing: -0.03em; margin-bottom: 6px; }}
  .login-card > p {{ font-size: 14px; color: var(--text-2); margin-bottom: 24px; }}
  .login-error {{
    background: rgba(239,68,68,0.1); color: var(--red); font-size: 13px;
    padding: 10px 12px; border-radius: 8px; margin-bottom: 16px;
  }}
  .btn-block {{ width: 100%; justify-content: center; }}
</style>
{{% block extra_head %}}{{% endblock %}}
</head>
<body>
{{% block body %}}{{% endblock %}}
{{% block scripts %}}{{% endblock %}}
</body>
</html>
'''

(ROOT / "myApp/templates/base.html").write_text(base, encoding="utf-8")

new_index = f'''{{% extends "base.html" %}}
{{% block title %}}CloseOut{{% endblock %}}
{{% block body %}}
{body_content}
{{% endblock %}}
{{% block scripts %}}
<script>
{app_script}
</script>
{{% endblock %}}
'''

index_path.write_text(new_index, encoding="utf-8")
print("Wrote base.html and refactored index.html")
