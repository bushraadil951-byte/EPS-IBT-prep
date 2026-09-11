workers = 1
worker_class = "gevent"
worker_connections = 100
timeout = 120
bind = "0.0.0.0:10000"
preload_app = True
max_requests = 1000
max_requests_jitter = 100
