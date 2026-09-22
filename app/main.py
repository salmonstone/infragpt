from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import PlainTextResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from config import settings
from database import init_db, get_db, User, ChatHistory
from auth import hash_password, verify_password, create_access_token, get_current_user, require_role
from cache import get_cached_answer, set_cached_answer, check_rate_limit
from llm import ask_llm
from metrics import (
    request_count, chat_latency, tokens_used,
    cache_hits, rate_limit_hits, metrics_output,
)
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="InfraGPT", version="2.0.0")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def startup():
    init_db()
    # Seed a default admin user if DB is empty
    db = next(get_db())
    if not db.query(User).first():
        db.add(User(username="admin", hashed_password=hash_password("admin123"), role="admin"))
        db.add(User(username="user1", hashed_password=hash_password("user123"), role="user"))
        db.commit()
    db.close()


# ---------- schemas ----------

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    tokens_used: int
    latency_ms: float
    cached: bool
    model: str


# ---------- routes ----------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/auth/login", response_model=LoginResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        request_count.labels("POST", "/auth/login", "401").inc()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token({"sub": user.username, "role": user.role})
    request_count.labels("POST", "/auth/login", "200").inc()
    return LoginResponse(access_token=token, role=user.role)


@app.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "readonly":
        raise HTTPException(status_code=403, detail="Read-only users cannot use chat")

    if not check_rate_limit(current_user.username):
        rate_limit_hits.inc()
        request_count.labels("POST", "/chat", "429").inc()
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in a minute.")

    question = body.message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Empty message")

    # Redis cache check
    cached = get_cached_answer(current_user.username, question)
    if cached:
        cache_hits.inc()
        request_count.labels("POST", "/chat", "200").inc()
        return ChatResponse(**cached, cached=True)

    # Call LLM with retry + fallback
    try:
        with chat_latency.time():
            result = ask_llm(question)
    except Exception as e:
        logger.error(f"LLM error: {e}")
        request_count.labels("POST", "/chat", "503").inc()
        raise HTTPException(status_code=503, detail="LLM service unavailable. Please retry.")

    tokens_used.labels(result["model"]).inc(result["tokens"])

    # Persist to PostgreSQL
    db.add(ChatHistory(
        username=current_user.username,
        question=question,
        answer=result["answer"],
        tokens_used=result["tokens"],
        latency_ms=result["latency_ms"],
    ))
    db.commit()

    response_data = {
        "reply": result["answer"],
        "tokens_used": result["tokens"],
        "latency_ms": result["latency_ms"],
        "model": result["model"],
    }
    set_cached_answer(current_user.username, question, response_data)

    request_count.labels("POST", "/chat", "200").inc()
    return ChatResponse(**response_data, cached=False)


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "InfraGPT",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    data, content_type = metrics_output()
    return PlainTextResponse(content=data, media_type=content_type)


@app.get("/history")
def history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin sees all history; users see their own."""
    if current_user.role == "admin":
        rows = db.query(ChatHistory).order_by(ChatHistory.created_at.desc()).limit(50).all()
    else:
        rows = (
            db.query(ChatHistory)
            .filter(ChatHistory.username == current_user.username)
            .order_by(ChatHistory.created_at.desc())
            .limit(20)
            .all()
        )
    return [
        {
            "question": r.question,
            "answer": r.answer[:200],
            "tokens": r.tokens_used,
            "latency_ms": r.latency_ms,
            "at": r.created_at.isoformat(),
        }
        for r in rows
    ]
