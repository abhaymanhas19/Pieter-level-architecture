
# Piter-level-architecture

In corporate tech, software architecture is usually optimized for infinite scale, high availability, and large engineering teams. Pieter Levels’ architecture is optimized for speed-to-market, absolute cost-minimization, and solo-operator survival
---------

### Examples
Think of traditional modern architecture like building a highly secure, automated, multi-lane highway system (using AWS/Google Cloud, Kubernetes, Docker, microservices, and CI/CD pipelines). It is powerful, but it takes months to plan and costs thousands of dollars before a single car drives on it.

`Builds a super-fast dirt road directly to the destination. He strips away all "middlemen" software:`
- No Docker/Containers: Code runs bare-metal directly on the operating system.
- No Cloud Overhead: He uses a basic Virtual Private Server (VPS) from Hetzner or DigitalOcean rather than complex cloud networks.
- No Dev Environment: He frequently tests and alters code live on production or relies on automated, ultra-fast server webhooks that deploy changes in under 5 seconds



**```People often ask: "How can a single $40 server handle millions of visitors on Nomad List or Remote OK without crashing?```**
-

__It works because of Server-Side Generation (SSG) and the elimination of database strain__.

1. When a user visits a traditional React app, the browser makes 10 different API requests to a server, the server asks a database, the database calculates the data, and sends it back. If 10,000 people do this at once, the database crashes.
2. In Levels’ architecture, a simple background script (a Cron Job) runs every few minutes, fetches the data, organizes it, and saves it as static text or a raw file. When a user visits, NGINX simply hands them that pre-built file. The database isn't even touched during the user visit. It requires almost zero CPU power

```bash
[ User Browser ] 
       │ (Interacts with simple, fast UI)
       ▼
[ Core Central Monolith ] <─── (Cheap VPS handles Auth, Payments, & Cron Jobs)
       │
       ├─► [ Cloudflare R2 / AWS S3 ] (For cheap, static image storage)
       │
       └─► [ External GPU API Workers ] (Python scripts on rented GPUs generate the AI images)
```


Instead of hosting complex AI models himself, his core PHP app acts as a traffic controller. It takes the user's request, sends a command to a specialized cloud GPU provider via an API, waits for the image to be generated, saves it to a static storage bucket, and displays it to the user.
=======
# Docx themes, Pieter Levels style

A learning example. It is **not** connected to Ailyze and does not touch the Django project.
It shows one background job (upload a .docx, extract themes, write a summary) built the way
Pieter Levels builds Photo AI: one web file, SQLite as the queue, workers that loop forever,
cron to keep them alive, and a health-check page.

Python standard library only. Nothing to install.

## The flow

```
1. User picks interview.docx and clicks Analyse
        │
        ▼
2. app.py  POST /upload
     - saves file        → data/uploads/<job_id>.docx
     - inserts row       → jobs table (status = queued)
     - writes status     → public/status/<job_id>.json  {"status":"queued"}
     - replies at once   → {"job_id": "..."}          (the request is done in milliseconds)
        │
        ▼
3. Browser asks every 2 s:  GET /status/<job_id>.json
     (just reads a file — in production Nginx serves it, Python is not involved)
        │
        ▼
4. worker.py  (3 copies, each looping forever)
     - claims the oldest queued row inside BEGIN IMMEDIATE, so two workers never take the same job
     - status = processing, attempts + 1
     - step 1  extract text from the docx            → progress 10%
     - step 2  split into chunks, themes per chunk   → progress 10–80%   (LLM call per chunk)
     - step 3  merge themes across chunks            → progress 85%
     - step 4  write a summary                       → progress 95%      (LLM call)
     - saves result      → data/results/<job_id>.json
     - row status = done, status file says done + result_url
        │
        ▼
5. Browser sees "done", fetches /result/<job_id>, shows themes + quotes + summary
```

If a step throws an error, the job goes back to `queued` and is retried, up to 3 attempts,
then it is marked `failed`.

## Where results are stored

| What | Where | Why |
|---|---|---|
| The uploaded file | `data/uploads/<job_id>.docx` | Input for the worker |
| Job state (queued / processing / done / failed, step, progress, attempts, errors) | `data/jobs.db` → `jobs` table (SQLite) | The queue **and** the record |
| Live progress for the browser | `public/status/<job_id>.json` | A static file is the cheapest thing to poll |
| The final analysis | `data/results/<job_id>.json` | The result, served by `/result/<job_id>` |

Files are written to a `.tmp` file and then renamed, so the browser never reads a half-written file.

## Files

| File | Role | Photo AI equivalent |
|---|---|---|
| `app.py` | Website, upload endpoint, status/result reads, `/healthcheck` | `index.php` |
| `worker.py` | The background job: extract, chunk, themes, merge, summary | `workers/worker.php` |
| `db.py` | SQLite connection (WAL mode), table, atomic file writes | inline in `index.php` |
| `ensure_workers.sh` | Starts workers until N are running | cron "restart dead workers" |
| `cleanup.py` | Puts jobs stuck in `processing` for 30 min back in the queue | an hourly worker script |
| `crontab.txt` | The two cron lines that run all of the above | `crontab -e` |
| `make_sample.py` | Builds a small test interview .docx | — |

## Run it

```bash
cd levels_docx_example
python3 make_sample.py                 # creates sample_interview.docx
python3 app.py                         # terminal 1 → open http://localhost:8765
WORKERS=3 ./ensure_workers.sh          # terminal 2 → starts 3 workers in the background
```

Upload `sample_interview.docx` in the browser and watch the progress bar.

- Without `OPENAI_API_KEY` it uses a simple offline word-count fallback, so it runs for free.
- With `OPENAI_API_KEY` set (and optional `LLM_MODEL`) it calls OpenAI for real themes and summary.
- Health page: http://localhost:8765/healthcheck
- Stop workers: `pkill -f levels_docx_example/worker.py`
- Reset everything: `rm -rf data public logs`

## Tested

8 uploads, 3 workers: all 8 finished, each ran exactly once (`attempts = 1`), work spread across
all three workers. A non-.docx upload is rejected. Healthcheck shows all green afterwards.

## How this compares with the real Ailyze docx pipeline

| This example | Ailyze today |
|---|---|
| `jobs` table in SQLite | Celery + Redis queue, state rows in Postgres |
| `worker.py` loop | Celery workers on `addfilequeue` / `themeandresearchquestion` |
| `ensure_workers.sh` via cron | supervisord / separate worker processes |
| `cleanup.py` via cron | Celery beat + stale-job sweeper |
| Polling a static JSON file | SSE progress stream |
| `/healthcheck` page | **Not present — the idea worth borrowing** |

## Where this design starts to hurt (and why Ailyze doesn't use it)

- **One writer at a time.** Every progress update is a write. Fine for 3 workers on one file.
  With many workers writing progress, chunks, codebook edits and search data at once, they queue
  up behind each other.
- **One document per job.** Ailyze's pipeline aggregates many documents into one project
  (frequency, viewpoints, overall analysis), with collaborators editing at the same time.
- **The 30-minute stuck rule.** `cleanup.py` assumes no job runs longer than 30 minutes. A real
  Ailyze analysis can run for hours, and this rule would start a duplicate copy while the first
  is still running.
- **No search inside the database.** Transcript search in Ailyze needs pgvector (Postgres only).
- **One machine.** The SQLite file lives on one disk, so workers cannot run on other servers.
>>>>>>> 2969252 (34)
