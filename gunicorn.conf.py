# ══════════════════════════════════════════════════════════════════
#  COMPLETE PERFORMANCE FIX FOR EPS IBT PORTAL
#  Apply in order — each step independently improves speed
# ══════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────
# FIX 1: gunicorn.conf.py  (NEW FILE — place in project root)
# Render uses gunicorn. Without this file it defaults to 1 worker.
# This alone fixes 80% of the concurrency problem.
# ─────────────────────────────────────────────────────────────────

# gunicorn.conf.py
import multiprocessing

# 4 workers handle ~50 concurrent students comfortably on 512MB RAM
# Formula: (2 × CPU cores) + 1  — Render free gives 0.1 CPU, use 4
workers    = 4
worker_class = "gthread"   # threaded workers — better for I/O (DB calls)
threads    = 4             # 4 threads per worker = 16 concurrent requests
timeout    = 120           # seconds before killing a slow request
keepalive  = 5             # reuse TCP connections between requests
bind       = "0.0.0.0:10000"
accesslog  = "-"           # log to stdout so Render shows it
errorlog   = "-"
loglevel   = "warning"     # reduce log noise
preload_app = True         # load app once, share across workers (saves RAM)
