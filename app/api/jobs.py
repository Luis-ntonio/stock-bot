from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from app.db.session import get_db
from app.db.crud import get_job, list_jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobResponse(BaseModel):
    id: int
    job_type: str
    ticker: str
    market: str | None
    position_id: int | None
    status: str
    result: dict | None
    error: str | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


@router.get("/{job_id}", response_model=JobResponse)
def get_job_endpoint(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/", response_model=list[JobResponse])
def list_jobs_endpoint(status: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    return list_jobs(db, status=status, limit=limit)
