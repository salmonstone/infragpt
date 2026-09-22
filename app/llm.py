import time
from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import settings

SYSTEM_PROMPT = """You are InfraGPT, an expert DevOps and AWS engineer assistant.
You help with: AWS (EC2, EKS, S3, IAM, VPC, Lambda, CloudWatch),
Docker, Kubernetes, Terraform, Jenkins, CI/CD, Prometheus, Grafana.
Always structure your answers:
1. Direct answer first
2. Code or commands in code blocks
3. Best practice tip at end
Use markdown formatting. Be concise but complete."""

MODELS = ["groq/compound", "llama3-8b-8192"]  # primary + fallback

client = Groq(api_key=settings.groq_api_key)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _call_llm(model: str, question: str) -> dict:
    start = time.time()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        max_tokens=1024,
        temperature=0.7,
        timeout=30,
    )
    latency_ms = (time.time() - start) * 1000
    return {
        "answer": response.choices[0].message.content,
        "tokens": response.usage.total_tokens if response.usage else 0,
        "latency_ms": round(latency_ms, 2),
        "model": model,
    }


def ask_llm(question: str) -> dict:
    last_error = None
    for model in MODELS:
        try:
            return _call_llm(model, question)
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(f"All LLM models failed: {last_error}")
