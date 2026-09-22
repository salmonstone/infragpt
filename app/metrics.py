from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

request_count = Counter(
    "infragpt_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

chat_latency = Histogram(
    "infragpt_chat_latency_seconds",
    "LLM response latency in seconds",
    buckets=[0.5, 1, 2, 5, 10, 30],
)

tokens_used = Counter(
    "infragpt_llm_tokens_total",
    "Total LLM tokens consumed",
    ["model"],
)

cache_hits = Counter("infragpt_cache_hits_total", "Redis cache hits")
rate_limit_hits = Counter("infragpt_rate_limit_hits_total", "Rate limit rejections")


def metrics_output():
    return generate_latest(), CONTENT_TYPE_LATEST
