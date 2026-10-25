"""Pagina «Feedback»: modulo per commenti, segnalazioni di bandi o posizioni ed errori.

Il sito è statico: i messaggi arrivano per email al proprietario tramite Web3Forms (servizio gratuito).
La chiave di accesso di Web3Forms è pubblica per natura (identifica solo la casella di destinazione) e va in
config.json come «feedback_key». Senza chiave la pagina mostra il modulo disattivato.
"""

from html import escape

import grants

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Feedback · {brand}</title>
<meta name="description" content="Tell us what to improve, suggest a funding call or a position, or report an error.">
{og}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  :root {{ --bg: {bg}; --card: #15304A; --text: #FFFFFF; --muted: {muted}; --soft: {soft}; --accent: {accent}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); font-family: Inter, system-ui, sans-serif; line-height: 1.5; }}
  .bar {{ height: 6px; background: var(--accent); }}
  main {{ max-width: 640px; margin: 0 auto; padding: 28px 16px 48px; }}
  .switch {{ display: inline-block; color: var(--text); text-decoration: none; font-size: 14px; font-weight: 600;
            border: 1px solid var(--muted); border-radius: 999px; padding: 7px 14px; margin: 0 6px 18px 0; }}
  .badge {{ display: inline-block; background: var(--accent); color: var(--bg); font-weight: 800; font-size: 13px;
           letter-spacing: .06em; padding: 6px 14px; border-radius: 999px; }}
  h1 {{ font-size: 30px; font-weight: 800; margin: 14px 0 6px; line-height: 1.15; }}
  .intro {{ color: var(--soft); margin: 0 0 20px; font-size: 15px; }}
  form {{ background: var(--card); border-radius: 18px; padding: 20px; display: grid; gap: 14px; }}
  label {{ display: grid; gap: 6px; font-size: 12px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
          color: var(--muted); }}
  label small {{ text-transform: none; letter-spacing: 0; font-weight: 500; color: var(--soft); font-size: 13px; }}
  input, select, textarea {{ font: 500 16px Inter, system-ui, sans-serif; color: var(--text); background: var(--bg);
                            border: 1px solid var(--muted); border-radius: 10px; padding: 11px 12px; width: 100%; }}
  textarea {{ min-height: 140px; resize: vertical; }}
  input:focus, select:focus, textarea:focus {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
  .hp {{ position: absolute; left: -9999px; width: 1px; height: 1px; overflow: hidden; }}
  button {{ background: var(--accent); color: var(--bg); border: 0; border-radius: 999px; padding: 13px 20px;
           font: 800 16px Inter, system-ui, sans-serif; cursor: pointer; }}
  button:disabled {{ opacity: .5; cursor: default; }}
  .note {{ color: var(--soft); font-size: 13px; margin: 0; }}
  .status {{ font-size: 15px; font-weight: 600; min-height: 1.5em; margin: 0; }}
  .status.ok {{ color: var(--accent); }}
  .status.err {{ color: #FF9B85; }}
  footer {{ color: var(--muted); font-size: 13px; margin-top: 30px; }}
  footer a {{ color: var(--accent); }}
</style>
</head>
<body>
<div class="bar"></div>
<main>
  <a class="switch" href="index.html">&larr; Home</a><a class="switch" href="calls.html">Funding calls &rarr;</a><a class="switch" href="positions.html">Positions &rarr;</a><br>
  <span class="badge">FEEDBACK</span>
  <h1>Help us improve the page</h1>
  <p class="intro">Something missing, wrong or hard to use? Know a call or a position we should add? Write to us: we read every message.</p>
  <form id="fb" action="https://api.web3forms.com/submit" method="POST">
    <input type="hidden" name="access_key" value="{key}">
    <input type="hidden" name="subject" value="Feedback from {brand_plain}">
    <input type="hidden" name="from_name" value="{brand_plain} website">
    <label>What is it about?
      <select name="topic" required>
        <option value="Feedback on the site">Feedback on the site</option>
        <option value="Suggest a funding call">Suggest a funding call</option>
        <option value="Suggest a position">Suggest an academic position</option>
        <option value="Report an error">Report an error in a call or position</option>
        <option value="Other">Other</option>
      </select>
    </label>
    <label>Your message
      <textarea name="message" required maxlength="3000" placeholder="Tell us what you think, or describe the call, position or error"></textarea>
    </label>
    <label>Link <small>(optional: the official call, advertisement or card you are writing about)</small>
      <input type="url" name="link" placeholder="https://" maxlength="500">
    </label>
    <label>Email <small>(optional, only if you want a reply)</small>
      <input type="email" name="email" autocomplete="email" maxlength="200">
    </label>
    <div class="hp" aria-hidden="true"><label>Leave this empty<input type="checkbox" name="botcheck" tabindex="-1"></label></div>
    <p class="note">Your message reaches the page owner by email through Web3Forms. We use it only to improve the page,
    we never publish it and we never share your email.</p>
    <button type="submit" {disabled}>Send</button>
    <p class="status" role="status" aria-live="polite">{status}</p>
  </form>
  <footer>Updated {updated} · <a href="https://www.instagram.com/{ig}/">{handle} on Instagram</a></footer>
</main>
<script>
(function () {{
  var f = document.getElementById("fb"), st = f.querySelector(".status"), btn = f.querySelector("button");
  try {{
    var q = new URLSearchParams(location.search), t = q.get("topic"), ref = q.get("ref");
    if (t) {{ var o = f.topic.querySelector('option[value="' + t + '"]'); if (o) f.topic.value = t; }}
    if (ref) f.link.value = location.origin + "/calls#" + ref.replace(/[^A-Za-z0-9-]/g, "");
  }} catch (e) {{}}
  if (!window.fetch || !window.FormData) return;          // browser vecchi: invio classico del modulo
  f.addEventListener("submit", function (ev) {{
    ev.preventDefault();
    if (btn.disabled) return;
    btn.disabled = true; st.className = "status"; st.textContent = "Sending…";
    fetch(f.action, {{ method: "POST", body: new FormData(f), headers: {{ "Accept": "application/json" }} }})
      .then(function (r) {{ return r.json().catch(function () {{ return {{}}; }}).then(function (j) {{ return r.ok && j.success !== false; }}); }})
      .then(function (ok) {{
        if (ok) {{ f.reset(); st.className = "status ok"; st.textContent = "Thank you! Your message has been sent."; }}
        else {{ st.className = "status err"; st.textContent = "Sorry, it did not work. Please try again in a few minutes."; }}
        btn.disabled = false;
      }})
      .catch(function () {{ st.className = "status err"; st.textContent = "No connection. Please try again."; btn.disabled = false; }});
  }});
}})();
</script>
</body>
</html>
"""


def build_page(cfg, today=None):
    from datetime import date
    c = cfg["colors"]
    key = (cfg.get("feedback_key") or "").strip()
    return PAGE.format(brand=escape(cfg["brand_name"]), brand_plain=escape(cfg["brand_name"], quote=True),
                       bg=c["background"], muted=c["muted"], soft=c["muted_text"], accent=c["accent"],
                       key=escape(key, quote=True), disabled="" if key else "disabled",
                       status="" if key else "The form will be active very soon.",
                       updated=grants._fmt_date(today or date.today()), ig=cfg["handle"].lstrip("@"),
                       handle=escape(cfg["handle"]),
                       og=grants.og_tags(cfg, f"Feedback · {cfg['brand_name']}",
                                         "Tell us what to improve, suggest a call or a position, or report an error.",
                                         "feedback"))
