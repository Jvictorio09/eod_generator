"""Restructure index.html: single bottom script + Phase 2 JS."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "myApp/templates/index.html"
text = p.read_text(encoding="utf-8")

title_marker = "<title>CloseOut</title>"
title_end = text.index(title_marker) + len(title_marker)
first_script_start = text.index("<script>", title_end)
first_script_end = text.index("</script>", first_script_start) + len("</script>")
main_script = text[first_script_start + len("<script>") : text.index("</script>", first_script_start)].strip()

head_middle = text[first_script_end : text.index("<body>", first_script_end)]
body_end = text.rindex("</body>")
last_script_start = text.rindex("<script>", 0, body_end)
body_content = text[text.index("<body>") : last_script_start]

theme_flash = """<script>
  (function () {
    var k = 'closeout:theme';
    var t = localStorage.getItem(k);
    if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
    else document.documentElement.setAttribute('data-theme',
      window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  })();
</script>"""

PHASE2_HELPERS = """
  let genFormat = 'PLAIN';

  function syncGenOptions() {
    genFormat = settings.format || 'PLAIN';
    document.querySelectorAll('.format-tab').forEach(tab => {
      tab.classList.toggle('active', tab.dataset.format === genFormat);
    });
    if ($('gen-tone')) $('gen-tone').value = settings.tone || 'professional';
    if ($('gen-length')) $('gen-length').value = settings.length || 'standard';
  }

  function timeToInput(val) {
    if (!val) return '';
    return val.slice(0, 5);
  }

  function inputToTime(val) {
    return val ? val + ':00' : null;
  }

  async function loadInsights() {
    try {
      const c = await api('/api/insights/consistency/');
      if ($('consistency-pct')) $('consistency-pct').textContent = c.active_days + '/' + c.window_days;
      if ($('consistency-msg')) $('consistency-msg').textContent = c.message;
      const w = await api('/api/insights/wins/');
      const box = $('wins-list');
      if (!box) return;
      if (!w.wins?.length) {
        box.innerHTML = '<div style="color:var(--text-3);font-size:12px">Wins appear as you complete tasks.</div>';
      } else {
        box.innerHTML = w.wins.map(win =>
          `<div class="win-item"><div class="win-date">${escapeHtml(win.date)}</div>${escapeHtml(win.title)}</div>`
        ).join('');
      }
    } catch (e) { console.error(e); }
  }

  async function runSearch() {
    const q = $('search-input').value.trim();
    if (q.length < 2) return;
    try {
      const d = await api('/api/search/?q=' + encodeURIComponent(q));
      const box = $('search-results');
      if (!d.results?.length) {
        box.innerHTML = '<div style="color:var(--text-3);padding:8px">No matches</div>';
        return;
      }
      box.innerHTML = d.results.map(r =>
        `<div class="search-hit" data-report="${r.type === 'report' ? r.id : ''}"><strong>${escapeHtml(r.title)}</strong><div class="meta">${escapeHtml(r.date)}${r.user ? ' · ' + escapeHtml(r.user) : ''}</div></div>`
      ).join('');
      box.querySelectorAll('[data-report]').forEach(el => {
        if (!el.dataset.report) return;
        el.onclick = async () => {
          const rep = await api('/api/reports/' + el.dataset.report + '/');
          openM('modal-report');
          $('report-output').innerHTML = `<div class="report">${escapeHtml(rep.content)}</div>`;
        };
      });
    } catch (e) { toast(e.message); }
  }
"""

if "let genFormat" not in main_script:
    main_script = main_script.replace(
        "  function escapeHtml(s) {",
        PHASE2_HELPERS + "\n  function escapeHtml(s) {",
    )

main_script = main_script.replace(
    "let settings = { name: '', dept: '', model: 'gpt-4o-mini', style: '', is_manager: false };",
    "let settings = { name: '', dept: '', model: 'gpt-4o-mini', style: '', is_manager: false, format: 'PLAIN', tone: 'professional', length: 'standard', timezone: 'UTC', auto_send_enabled: false };",
)

main_script = main_script.replace(
    """    settings = {
      name: p.display_name || '',
      dept: p.department || '',
      model: p.ai_model || 'gpt-4o-mini',
      style: p.style_guide || '',
      is_manager: !!p.is_manager,
    };
    updateUser();""",
    """    settings = {
      name: p.display_name || '',
      dept: p.department || '',
      model: p.ai_model || 'gpt-4o-mini',
      style: p.style_guide || '',
      is_manager: !!p.is_manager,
      format: p.default_format || 'PLAIN',
      tone: p.default_tone || 'professional',
      length: p.default_length || 'standard',
      timezone: p.timezone || 'UTC',
      auto_send_enabled: !!p.auto_send_enabled,
      auto_send_time: p.auto_send_time,
      quiet_hours_start: p.quiet_hours_start,
      quiet_hours_end: p.quiet_hours_end,
    };
    updateUser();
    syncGenOptions();
    loadInsights();""",
)

main_script = main_script.replace(
    """  $('btn-settings').onclick = () => {
    $('settings-name').value = settings.name || '';
    $('settings-dept').value = settings.dept || '';
    $('settings-model').value = settings.model || 'gpt-4o-mini';
    $('settings-style').value = settings.style || '';
    $('settings-theme').value = getThemePref();
    openM('modal-settings');
  };""",
    """  $('btn-settings').onclick = () => {
    $('settings-name').value = settings.name || '';
    $('settings-dept').value = settings.dept || '';
    $('settings-model').value = settings.model || 'gpt-4o-mini';
    $('settings-style').value = settings.style || '';
    $('settings-theme').value = getThemePref();
    $('settings-format').value = settings.format || 'PLAIN';
    $('settings-tone').value = settings.tone || 'professional';
    $('settings-length').value = settings.length || 'standard';
    $('settings-timezone').value = settings.timezone || 'UTC';
    $('settings-auto-send').checked = !!settings.auto_send_enabled;
    $('settings-send-time').value = timeToInput(settings.auto_send_time);
    $('settings-quiet-start').value = timeToInput(settings.quiet_hours_start);
    $('settings-quiet-end').value = timeToInput(settings.quiet_hours_end);
    openM('modal-settings');
  };""",
)

main_script = main_script.replace(
    """      await api('/api/profile/update/', {
        method: 'POST',
        body: JSON.stringify({
          display_name: settings.name,
          department: settings.dept,
          ai_model: settings.model,
          style_guide: settings.style,
        }),
      });
      updateUser();
      closeM('modal-settings');
      toast('Saved');""",
    """      settings.format = $('settings-format').value;
      settings.tone = $('settings-tone').value;
      settings.length = $('settings-length').value;
      settings.timezone = $('settings-timezone').value.trim() || 'UTC';
      settings.auto_send_enabled = $('settings-auto-send').checked;
      await api('/api/profile/update/', {
        method: 'POST',
        body: JSON.stringify({
          display_name: settings.name,
          department: settings.dept,
          ai_model: settings.model,
          style_guide: settings.style,
          default_format: settings.format,
          default_tone: settings.tone,
          default_length: settings.length,
          timezone: settings.timezone,
          auto_send_enabled: settings.auto_send_enabled,
          auto_send_time: inputToTime($('settings-send-time').value),
          quiet_hours_start: inputToTime($('settings-quiet-start').value),
          quiet_hours_end: inputToTime($('settings-quiet-end').value),
        }),
      });
      syncGenOptions();
      updateUser();
      closeM('modal-settings');
      toast('Saved');""",
)

main_script = main_script.replace(
    "const d = await api('/api/generate-eod/', { method: 'POST', body: JSON.stringify({ model: settings.model }) });",
    "const d = await api('/api/generate-eod/', { method: 'POST', body: JSON.stringify({ model: settings.model, format: genFormat, tone: $('gen-tone').value, length: $('gen-length').value, date: todayISO() }) });",
)

main_script = main_script.replace(
    """          Object.assign(t, d.task);
          render();
        } catch (e) { toast(e.message); }
      };
    });

    document.querySelectorAll('[data-block]').forEach(el => {""",
    """          Object.assign(t, d.task);
          render();
          if (next === 'DONE') loadInsights();
        } catch (e) { toast(e.message); }
      };
    });

    document.querySelectorAll('[data-block]').forEach(el => {""",
)

main_script = main_script.replace(
    """  $('btn-copy').onclick = async () => {""",
    """  document.querySelectorAll('.format-tab').forEach(tab => {
    tab.onclick = () => {
      genFormat = tab.dataset.format;
      document.querySelectorAll('.format-tab').forEach(t => t.classList.toggle('active', t === tab));
    };
  });

  $('btn-week-review').onclick = async () => {
    $('btn-week-review').disabled = true;
    $('week-review-out').style.display = 'block';
    $('week-review-out').textContent = 'Generating…';
    try {
      const d = await api('/api/week-review/', { method: 'POST', body: '{}' });
      $('week-review-out').textContent = d.review;
    } catch (e) {
      $('week-review-out').textContent = e.message;
    }
    $('btn-week-review').disabled = false;
  };

  $('btn-search').onclick = runSearch;
  $('search-input').onkeydown = e => { if (e.key === 'Enter') runSearch(); };

  $('btn-copy').onclick = async () => {""",
)

main_script = main_script.replace(
    """  (async function init() {
    $('today-date').textContent = new Date().toLocaleDateString('en-US', {
      weekday: 'long', month: 'short', day: 'numeric', year: 'numeric'
    });
    try {
      await loadProfile();""",
    """  (async function init() {
    applyTheme(getThemePref(), false);
    $('today-date').textContent = new Date().toLocaleDateString('en-US', {
      weekday: 'long', month: 'short', day: 'numeric', year: 'numeric'
    });
    try {
      await loadProfile();""",
)

new_text = (
    "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
    "<meta charset=\"UTF-8\" />\n"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\"/>\n"
    f"<title>CloseOut</title>\n{theme_flash}\n"
    f"{head_middle}\n{body_content}\n<script>\n{main_script}\n</script>\n</body>\n</html>\n"
)
p.write_text(new_text, encoding="utf-8")
print("Wrote", p, "—", len(new_text), "chars, 1 script block")
