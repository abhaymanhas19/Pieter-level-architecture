import json
import re
import secrets
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from db import RESULTS, STATUS, UPLOADS, connect, write_status

MAX_UPLOAD = 20 * 1024 * 1024
JOB_ID = r"[a-f0-9]{16}"

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Docx themes</title>
<style>
body{font-family:system-ui;max-width:720px;margin:40px auto;padding:0 16px}
#bar{height:10px;background:#eee;border-radius:5px;overflow:hidden;margin:12px 0}
#fill{height:100%;width:0;background:#4a7;transition:width .3s}
li{margin:10px 0} blockquote{color:#555;margin:4px 0 0 12px;font-size:14px}
</style></head><body>
<h1>Upload a .docx, get themes</h1>
<input type="file" id="file" accept=".docx"> <button id="go">Analyse</button>
<div id="bar"><div id="fill"></div></div>
<div id="step"></div>
<h2 id="h" hidden>Summary</h2><p id="summary"></p><ol id="themes"></ol>
<script>
const $ = id => document.getElementById(id);
$('go').onclick = async () => {
  const f = $('file').files[0];
  if (!f) return;
  const r = await fetch('/upload', {method:'POST', body:f, headers:{'X-Filename': encodeURIComponent(f.name)}});
  const {job_id, error} = await r.json();
  if (error) { $('step').textContent = error; return; }
  const timer = setInterval(async () => {
    const s = await fetch('/status/' + job_id + '.json');
    if (!s.ok) return;
    const st = await s.json();
    $('fill').style.width = (st.progress || 0) + '%';
    $('step').textContent = st.status + (st.step ? ' - ' + st.step : '') + (st.error ? ' - ' + st.error : '');
    if (st.status === 'failed') clearInterval(timer);
    if (st.status === 'done') { clearInterval(timer); render(await (await fetch(st.result_url)).json()); }
  }, 2000);
};
function render(res) {
  $('h').hidden = false;
  $('summary').textContent = res.summary;
  $('themes').innerHTML = '';
  for (const t of res.themes) {
    const li = document.createElement('li');
    li.textContent = t.name + ' (' + t.count + ')';
    for (const q of t.quotes) { const b = document.createElement('blockquote'); b.textContent = '"' + q + '"'; li.appendChild(b); }
    $('themes').appendChild(li);
  }
}
</script></body></html>"""


def healthcheck():
    conn = connect()
    now = int(time.time())

    def count(sql, *args):
        return conn.execute(sql, args).fetchone()[0]

    usage = shutil.disk_usage("/")
    checks = [
        ("Jobs finished in last 24h", count("SELECT COUNT(*) FROM jobs WHERE status='done' AND finished_at > ?", now - 86400) > 0),
        ("Nothing queued longer than 10 min", count("SELECT COUNT(*) FROM jobs WHERE status='queued' AND created_at < ?", now - 600) == 0),
        ("Nothing processing longer than 30 min", count("SELECT COUNT(*) FROM jobs WHERE status='processing' AND started_at < ?", now - 1800) == 0),
        ("Fewer than 5 failures in last hour", count("SELECT COUNT(*) FROM jobs WHERE status='failed' AND created_at > ?", now - 3600) < 5),
        ("Disk more than 10% free", usage.free / usage.total > 0.10),
    ]
    conn.close()
    return "<br>".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks)


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, body, content_type="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_json_file(self, path):
        if path.exists():
            return self.reply(200, path.read_bytes())
        return self.reply(404, '{"error":"not found"}')

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            return self.reply(200, PAGE, "text/html; charset=utf-8")
        if path == "/healthcheck":
            return self.reply(200, healthcheck(), "text/html; charset=utf-8")
        match = re.fullmatch(rf"/status/({JOB_ID})\.json", path)
        if match:
            return self.serve_json_file(STATUS / f"{match[1]}.json")
        match = re.fullmatch(rf"/result/({JOB_ID})", path)
        if match:
            return self.serve_json_file(RESULTS / f"{match[1]}.json")
        self.reply(404, '{"error":"not found"}')

    def do_POST(self):
        if self.path != "/upload":
            return self.reply(404, '{"error":"not found"}')
        length = int(self.headers.get("Content-Length") or 0)
        name = unquote(self.headers.get("X-Filename", "upload.docx"))[:200]
        if not name.lower().endswith(".docx") or not 0 < length <= MAX_UPLOAD:
            return self.reply(400, '{"error":"send a .docx under 20 MB"}')

        job_id = secrets.token_hex(8)
        (UPLOADS / f"{job_id}.docx").write_bytes(self.rfile.read(length))
        conn = connect()
        conn.execute("INSERT INTO jobs (id, filename, created_at) VALUES (?, ?, ?)", (job_id, name, int(time.time())))
        conn.close()
        write_status(job_id, {"status": "queued", "progress": 0})
        self.reply(202, json.dumps({"job_id": job_id}))


if __name__ == "__main__":
    connect().close()
    print("http://localhost:8765")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
