import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.models import DrivingLog, Event, Trip
from app.db.session import get_db
from app.pipeline.cleansing import cleanse
from app.pipeline.detection import detect
from app.pipeline.segmentation import calc_distance_km, segment
from app.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    EventResponse,
    TripDetailResponse,
    TripResult,
)
from app.types import Zone
from app.utils.geo import add_bbox

_ZONES_PATH = Path(__file__).parent.parent.parent / "data" / "restricted_zones.json"

try:
    _ZONES: list[Zone] = add_bbox(json.loads(_ZONES_PATH.read_text()))
    _ZONES_LOADED = True
except (FileNotFoundError, json.JSONDecodeError):
    _ZONES = []
    _ZONES_LOADED = False

MAX_RECORDS = 100_000


def _trip_hash(records: list) -> str:
    content = json.dumps(
        [{"t": r["timestamp"], "la": r["gps_lat"], "lo": r["gps_lon"], "s": r["speed"]} for r in records]
    )
    return hashlib.sha256(content.encode()).hexdigest()


router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest, db: Session = Depends(get_db)):
    if not _ZONES_LOADED:
        raise HTTPException(status_code=500, detail=f"restricted_zones.json not found: {_ZONES_PATH}")
    if len(request.records) > MAX_RECORDS:
        raise HTTPException(status_code=413, detail=f"Too many records: limit is {MAX_RECORDS}")
    records = [r.model_dump() for r in request.records]

    cleaned = cleanse(records)
    trips = segment(cleaned)

    results: list[TripResult] = []

    for trip_records in trips:
        if not trip_records:
            continue

        h = _trip_hash(trip_records)
        existing = db.execute(select(Trip).where(Trip.source_hash == h)).scalar_one_or_none()
        if existing is not None:
            results.append(TripResult(trip_id=existing.id, event_count=len(existing.events)))
            continue

        distance_km = calc_distance_km(trip_records)
        events = detect(trip_records, _ZONES)

        trip = Trip(
            start_time=trip_records[0]["timestamp"],
            end_time=trip_records[-1]["timestamp"],
            distance_km=distance_km,
            record_count=len(trip_records),
            source_hash=h,
        )
        db.add(trip)
        db.flush()

        db.execute(insert(DrivingLog), [
            {
                "trip_id": trip.id,
                "timestamp": r["timestamp"],
                "gps_lat": r["gps_lat"],
                "gps_lon": r["gps_lon"],
                "speed": r["speed"],
            }
            for r in trip_records
        ])

        if events:
            db.execute(insert(Event), [
                {
                    "trip_id": trip.id,
                    "event_type": e["event_type"],
                    "timestamp": e["timestamp"],
                    "detail": e["detail"],
                }
                for e in events
            ])

        results.append(TripResult(trip_id=trip.id, event_count=len(events)))

    db.commit()

    return AnalyzeResponse(trip_count=len(results), trips=results)


@router.get("/trips/{trip_id}", response_model=TripDetailResponse)
def get_trip(trip_id: int, db: Session = Depends(get_db)):
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")

    events = [
        EventResponse(
            id=e.id,
            event_type=e.event_type,
            timestamp=e.timestamp,
            detail=json.loads(e.detail) if e.detail else None,
        )
        for e in trip.events
    ]

    return TripDetailResponse(
        id=trip.id,
        start_time=trip.start_time,
        end_time=trip.end_time,
        duration_seconds=trip.end_time - trip.start_time,
        distance_km=trip.distance_km,
        record_count=trip.record_count,
        events=events,
    )
