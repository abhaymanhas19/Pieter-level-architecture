import time

from db import connect, write_status

STUCK_AFTER = 30 * 60

conn = connect()
cutoff = int(time.time()) - STUCK_AFTER
stuck = conn.execute("SELECT id FROM jobs WHERE status='processing' AND started_at < ?", (cutoff,)).fetchall()
for row in stuck:
    conn.execute("UPDATE jobs SET status='queued', worker=NULL WHERE id=? AND status='processing'", (row["id"],))
    write_status(row["id"], {"status": "queued", "progress": 0})
print(f"requeued {len(stuck)} stuck job(s)")
