from fastapi import FastAPI, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal, engine
import models
from utils import normalize_event, generate_hash
import uuid
import datetime

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

def get_db():
    return SessionLocal()

@app.post("/ingest")
def ingest_event(event: dict, simulate_failure: bool = False):
    db: Session = get_db()

    # Store raw event
    raw_event = models.RawEvent(
        id=str(uuid.uuid4()),
        payload=event
    )
    db.add(raw_event)
    db.commit()

    normalized = normalize_event(event)
    event_hash = generate_hash(normalized)

    # Check if already processed
    existing = db.query(models.ProcessingState).filter_by(event_hash=event_hash).first()
    if existing and existing.status == "processed":
        return {"message": "Duplicate ignored"}

    try:
        # Mark processing
        state = models.ProcessingState(
            event_hash=event_hash,
            status="processing",
            last_attempt=datetime.datetime.utcnow()
        )
        db.merge(state)
        db.commit()

        # Simulate failure
        if simulate_failure:
            raise Exception("Simulated failure")

        # Store processed event
        processed = models.ProcessedEvent(
            event_hash=event_hash,
            client_id=normalized["client_id"],
            metric=normalized["metric"],
            amount=normalized["amount"],
            timestamp=normalized["timestamp"]
        )
        db.merge(processed)

        # Mark success
        state.status = "processed"
        db.commit()

        return {"message": "Processed"}

    except Exception as e:
        state.status = "failed"
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))