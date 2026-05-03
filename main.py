from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from database import SessionLocal, engine
import models
from utils import normalize_event, generate_hash
import uuid
import datetime

models.Base.metadata.create_all(bind=engine)

app = FastAPI()


# DB session handler
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Home UI
@app.get("/", response_class=HTMLResponse)
def home():
    with open("index.html") as f:
        return f.read()


# Ingestion API
@app.post("/ingest")
def ingest_event(event: dict, simulate_failure: bool = False, db: Session = Depends(get_db)):

    # Store raw event
    raw_event = models.RawEvent(
        id=str(uuid.uuid4()),
        payload=event
    )
    db.add(raw_event)

    normalized = normalize_event(event)
    event_hash = generate_hash(normalized)

    try:
        # Idempotency gate
        state = models.ProcessingState(
            event_hash=event_hash,
            status="processing",
            last_attempt=datetime.datetime.utcnow()
        )
        db.add(state)
        db.commit()

    except IntegrityError:
        db.rollback()

        existing = db.query(models.ProcessingState).filter_by(event_hash=event_hash).first()

        if existing and existing.status == "processed":
            return {"message": "Duplicate ignored"}

        state = existing

    try:
        if simulate_failure:
            raise Exception("Simulated failure")

        processed = models.ProcessedEvent(
            event_hash=event_hash,
            client_id=normalized["client_id"],
            metric=normalized["metric"],
            amount=normalized["amount"],
            timestamp=normalized["timestamp"]
        )
        db.add(processed)

        state.status = "processed"
        state.last_attempt = datetime.datetime.utcnow()

        db.commit()

        return {"message": "Processed successfully"}

    except Exception as e:
        db.rollback()

        state.status = "failed"
        state.last_attempt = datetime.datetime.utcnow()
        db.commit()

        raise HTTPException(status_code=500, detail=str(e))


# Aggregation API
@app.get("/aggregate")
def aggregate(db: Session = Depends(get_db)):
    events = db.query(models.ProcessedEvent).all()

    total_amount = sum(e.amount for e in events)
    count = len(events)

    return {
        "total_amount": total_amount,
        "count": count
    }


# Debug APIs
@app.get("/events/processed")
def get_processed(db: Session = Depends(get_db)):
    return db.query(models.ProcessedEvent).all()


@app.get("/events/failed")
def get_failed(db: Session = Depends(get_db)):
    return db.query(models.ProcessingState).filter_by(status="failed").all()
