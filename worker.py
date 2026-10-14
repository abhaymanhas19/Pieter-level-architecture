import json
import os
import re
import socket
import sys
import time
import urllib.request
import zipfile
from collections import Counter
from xml.etree import ElementTree

from db import RESULTS, UPLOADS, connect, write_json, write_status

MAX_LIFETIME = int(os.environ.get("WORKER_MAX_LIFETIME", 24 * 3600))
MAX_ATTEMPTS = 3
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
STOPWORDS = set(
    "the a an and or but of to in on for with is are was were be been it its this that as at by from "
    "we i you they he she our their them not have has had do does did so if then than there what "
    "which who will would can could just really very about also more some when into because like "
    "interviewer respondent feel".split()
)

THEME_PROMPT = (
    "Extract up to 5 themes from this interview text. "
    'Reply as JSON {"themes":[{"name":str,"quote":str}]} where quote is copied verbatim.\n\n'
)
SUMMARY_PROMPT = 'Write a 3-sentence summary of these themes. Reply as JSON {"summary":str}.\n\n'


def claim(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        job = conn.execute(
            "SELECT id, filename FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if job:
            conn.execute(
                "UPDATE jobs SET status='processing', worker=?, started_at=?, attempts=attempts+1 WHERE id=?",
                (WORKER_ID, int(time.time()), job["id"]),
            )
        conn.execute("COMMIT")
        return job
    except Exception:
        conn.execute("ROLLBACK")
        raise


def report(conn, job_id, step, progress):
    conn.execute("UPDATE jobs SET step=?, progress=? WHERE id=?", (step, progress, job_id))
    write_status(job_id, {"status": "processing", "step": step, "progress": progress})


def extract_paragraphs(path):
    with zipfile.ZipFile(path) as docx:
        root = ElementTree.fromstring(docx.read("word/document.xml"))
    paragraphs = []
    for p in root.iter(f"{W}p"):
        text = "".join(t.text or "" for t in p.iter(f"{W}t")).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def split_chunks(paragraphs, max_chars=6000):
    chunks, current = [], ""
    for p in paragraphs:
        if current and len(current) + len(p) > max_chars:
            chunks.append(current)
            current = ""
        current += p + "\n"
    if current:
        chunks.append(current)
    return chunks


def llm(prompt):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    body = json.dumps({
        "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }).encode()
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(json.loads(response.read())["choices"][0]["message"]["content"])


def themes_for_chunk(text):
    answer = llm(THEME_PROMPT + text)
    if answer:
        return answer.get("themes", [])
    words = [w for w in re.findall(r"[a-z']{4,}", text.lower()) if w not in STOPWORDS]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    themes = []
    for word, _ in Counter(words).most_common(5):
        quote = next((s for s in sentences if word in s.lower()), "")
        themes.append({"name": word, "quote": quote.strip()[:300]})
    return themes


def merge(themes_per_chunk):
    merged = {}
    for themes in themes_per_chunk:
        for theme in themes:
            entry = merged.setdefault(theme["name"].strip().lower(), {"name": theme["name"], "count": 0, "quotes": []})
            entry["count"] += 1
            if theme.get("quote") and len(entry["quotes"]) < 3:
                entry["quotes"].append(theme["quote"])
    return sorted(merged.values(), key=lambda e: -e["count"])


def summarise(themes):
    answer = llm(SUMMARY_PROMPT + json.dumps(themes[:15]))
    if answer:
        return answer.get("summary", "")
    return "Top themes: " + ", ".join(t["name"] for t in themes[:5]) + "."


def process(conn, job):
    job_id = job["id"]
    report(conn, job_id, "extracting text", 10)
    paragraphs = extract_paragraphs(UPLOADS / f"{job_id}.docx")
    if not paragraphs:
        raise ValueError("document has no text")
    chunks = split_chunks(paragraphs)

    themes_per_chunk = []
    for i, chunk in enumerate(chunks, 1):
        report(conn, job_id, f"theme extraction {i}/{len(chunks)}", 10 + int(70 * i / len(chunks)))
        themes_per_chunk.append(themes_for_chunk(chunk))

    report(conn, job_id, "merging themes", 85)
    themes = merge(themes_per_chunk)
    report(conn, job_id, "writing summary", 95)

    write_json(RESULTS, job_id, {
        "job_id": job_id,
        "filename": job["filename"],
        "paragraphs": len(paragraphs),
        "chunks": len(chunks),
        "themes": themes,
        "summary": summarise(themes),
    })
    conn.execute(
        "UPDATE jobs SET status='done', step='done', progress=100, finished_at=? WHERE id=?",
        (int(time.time()), job_id),
    )
    write_status(job_id, {"status": "done", "progress": 100, "result_url": f"/result/{job_id}"})


def fail(conn, job, error):
    attempts = conn.execute("SELECT attempts FROM jobs WHERE id=?", (job["id"],)).fetchone()["attempts"]
    status = "failed" if attempts >= MAX_ATTEMPTS else "queued"
    message = str(error)[:500]
    conn.execute("UPDATE jobs SET status=?, error=?, worker=NULL WHERE id=?", (status, message, job["id"]))
    write_status(job["id"], {"status": status, "progress": 0, "error": message if status == "failed" else None})
    print(f"[{WORKER_ID}] job {job['id']} -> {status}: {message}", file=sys.stderr, flush=True)


def main():
    conn = connect()
    started = time.time()
    print(f"[{WORKER_ID}] started", flush=True)
    while time.time() - started < MAX_LIFETIME:
        job = claim(conn)
        if not job:
            time.sleep(1)
            continue
        print(f"[{WORKER_ID}] processing {job['id']} ({job['filename']})", flush=True)
        try:
            process(conn, job)
            print(f"[{WORKER_ID}] done {job['id']}", flush=True)
        except Exception as error:
            fail(conn, job, error)
    print(f"[{WORKER_ID}] lifetime reached, exiting so cron starts a fresh one", flush=True)


if __name__ == "__main__":
    main()
