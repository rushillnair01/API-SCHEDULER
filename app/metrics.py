from prometheus_client import Counter, Histogram

# Tracks every outgoing HTTP request by terminal status label.
# Usage: TOTAL_REQUESTS.labels(status="SUCCESS").inc()
TOTAL_REQUESTS = Counter(
    "scheduler_requests_total",
    "Total HTTP requests made by the scheduler",
    ["status"],          # label values: SUCCESS, FAILURE, INTERRUPTED
)

# Tracks wall-clock latency of each outgoing HTTP call.
# Usage (context-manager form):
#   with HTTP_REQUEST_DURATION.time():
#       response = requests.get(...)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Latency of outgoing HTTP requests in seconds",
    # Default buckets cover 5ms → 10s, which is appropriate for API calls
    # with a 10-second timeout set in tasks.py.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)