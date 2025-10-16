
import os
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, and_
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from celery import Celery

from .schemas import TaskRequest, AcknowledgementResponse
from .models import Base, Task

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))
EXPECTED_SECRET = os.getenv("EXPECTED_SECRET")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")

# Database setup
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

# Celery setup
celery_app = Celery("worker", broker=REDIS_URL)

app = FastAPI()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
def read_root():
    return {"message": "Welcome to the Student API Server!"}

@app.post("/api-endpoint", response_model=AcknowledgementResponse)
def api_endpoint(request: TaskRequest, db: Session = Depends(get_db)):
    # Validate secret
    if request.secret != EXPECTED_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid secret.")

    # Check for existing successful task
    existing = db.query(Task).filter(
        Task.nonce == request.nonce,
        Task.round == request.round,
        Task.status == "COMPLETE"
    ).first()
    if existing:
        # Return stored results (for now, just acknowledge)
        return AcknowledgementResponse(status=existing.status, task=existing.task_name, nonce=existing.nonce)

    # Create new task record
    new_task = Task(
        nonce=request.nonce,
        status="RECEIVED",
        email=request.email,
        task_name=request.task,
        round=request.round
    )
    db.add(new_task)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # If a task with this nonce already exists, return its state (idempotent)
        existing_task = db.query(Task).filter(Task.nonce == request.nonce, Task.round == request.round).first()
        if existing_task:
            return AcknowledgementResponse(status=existing_task.status, task=existing_task.task_name, nonce=existing_task.nonce)
        # Fallback
        raise HTTPException(status_code=409, detail="A task with this nonce already exists.")
    except Exception:
        db.rollback()
        raise
    db.refresh(new_task)

    # Dispatch background job to Celery
    celery_app.send_task("workers.tasks.process_task", args=[new_task.id])

    # Return immediate acknowledgement
    return AcknowledgementResponse(status="RECEIVED", task=request.task, nonce=request.nonce)
