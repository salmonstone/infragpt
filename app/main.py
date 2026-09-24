from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import PlainTextResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List
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
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Seed bootstrap users if the DB is empty. Credentials come from settings
    # (env-overridable) rather than being hard-coded — see config.py.
    db = next(get_db())
    try:
        if not db.query(User).first():
            db.add(User(
                username=settings.seed_admin_username,
                hashed_password=hash_password(settings.seed_admin_password),
                role="admin",
            ))
            db.add(User(
                username=settings.seed_user_username,
                hashed_password=hash_password(settings.seed_user_password),
                role="user",
            ))
            try:
                db.commit()
            except IntegrityError:
                # A sibling Uvicorn worker's lifespan hook won the same race
                # and already inserted these usernames — nothing to do.
                db.rollback()
    finally:
        db.close()
    yield


app = FastAPI(title="InfraGPT", version="2.0.0", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


# ---------- schemas ----------

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=6)


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    tokens_used: int
    latency_ms: float
    cached: bool
    model: str


class UserSummary(BaseModel):
    username: str
    role: str
    created_at: str


class RoleUpdateRequest(BaseModel):
    role: str = Field(pattern="^(admin|user|readonly)$")


# ---------- helpers ----------

def _history_rows(db: Session, username: str, limit: int = 50):
    rows = (
        db.query(ChatHistory)
        .filter(ChatHistory.username == username)
        .order_by(ChatHistory.created_at.desc())
        .limit(limit)
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


@app.post("/auth/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Self-service signup. Role is always "user" — never accepted from the
    client, so registering can't be used to grant yourself admin/readonly."""
    username = body.username.strip()
    if db.query(User).filter(User.username == username).first():
        request_count.labels("POST", "/auth/register", "409").inc()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    user = User(username=username, hashed_password=hash_password(body.password), role="user")
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with a concurrent registration of the same username.
        db.rollback()
        request_count.labels("POST", "/auth/register", "409").inc()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    token = create_access_token({"sub": user.username, "role": user.role})
    request_count.labels("POST", "/auth/register", "201").inc()
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

    # 1. Redis cache — fastest path, 5min TTL, exact question match.
    cached = get_cached_answer(current_user.username, question)
    if cached:
        cache_hits.inc()
        request_count.labels("POST", "/chat", "200").inc()
        return ChatResponse(**cached, cached=True)

    # 2. Postgres — has this exact question been asked before, ever? Durable
    # beyond Redis's 5min window. Reusing it also means we skip the AI call
    # entirely, so it's not "answered with today's context" — it's literally
    # the same question getting the same answer it got last time.
    prior = (
        db.query(ChatHistory)
        .filter(ChatHistory.username == current_user.username, ChatHistory.question == question)
        .order_by(ChatHistory.created_at.desc())
        .first()
    )
    if prior:
        response_data = {
            "reply": prior.answer,
            "tokens_used": prior.tokens_used,
            "latency_ms": prior.latency_ms,
            "model": "cached",
        }
        set_cached_answer(current_user.username, question, response_data)  # warm Redis for next time
        cache_hits.inc()
        request_count.labels("POST", "/chat", "200").inc()
        return ChatResponse(**response_data, cached=True)

    # 3. Neither cache nor history has it — actually ask the LLM. Give it the
    # last few turns of this user's own conversation so follow-ups ("explain
    # that more") work, instead of treating every message as standalone.
    recent = (
        db.query(ChatHistory)
        .filter(ChatHistory.username == current_user.username)
        .order_by(ChatHistory.created_at.desc())
        .limit(3)
        .all()
    )
    history = []
    for row in reversed(recent):  # oldest first, matching conversation order
        history.append({"role": "user", "content": row.question})
        history.append({"role": "assistant", "content": row.answer})

    try:
        with chat_latency.time():
            result = ask_llm(question, history=history)
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
    """Always just the caller's own chats — including for admins. An admin
    browsing someone else's history is a deliberate, separate action via
    GET /admin/users/{username}/history, not something that happens by
    default just from being logged in as admin."""
    return _history_rows(db, current_user.username, limit=20)


@app.get("/admin/users", response_model=List[UserSummary])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    users = db.query(User).order_by(User.created_at.asc()).all()
    return [
        UserSummary(username=u.username, role=u.role, created_at=u.created_at.isoformat())
        for u in users
    ]


@app.get("/admin/users/{username}/history")
def user_history(
    username: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    if not db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=404, detail="User not found")
    return _history_rows(db, username, limit=50)


@app.patch("/admin/users/{username}/role")
def update_user_role(
    username: str,
    body: RoleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target.role == "admin" and body.role != "admin":
        remaining_admins = db.query(User).filter(User.role == "admin", User.username != username).count()
        if remaining_admins == 0:
            raise HTTPException(status_code=400, detail="Cannot demote the last remaining admin")

    target.role = body.role
    db.commit()
    return {"username": target.username, "role": target.role}
