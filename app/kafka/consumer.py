"""
Kafka consumer — driving-logs 토픽을 구독하여 파이프라인을 실행하고 DB에 적재한다.

수신된 레코드는 FLUSH_INTERVAL(초) 단위로 버퍼링 후 일괄 처리한다.
cleansing/segmentation이 레코드 시퀀스 전체를 필요로 하기 때문에
단건 처리가 아닌 시간 윈도우 기반 배치 처리를 택했다.
"""
import hashlib
import json
import logging
import os
import time
from pathlib import Path

from kafka import KafkaConsumer
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.db.models import DrivingLog, Event, Trip
from app.db.session import SessionLocal, init_db
from app.pipeline.cleansing import cleanse
from app.pipeline.detection import detect
from app.pipeline.segmentation import calc_distance_km, segment
from app.types import Zone
from app.utils.geo import add_bbox

TOPIC = os.getenv("KAFKA_TOPIC", "driving-logs")
BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")
FLUSH_INTERVAL = int(os.getenv("FLUSH_INTERVAL", "10"))    # seconds
MAX_BUFFER_SIZE = int(os.getenv("MAX_BUFFER_SIZE", "50000"))  # OOM 방어: 레코드 수 상한

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_ZONES_PATH = Path(__file__).parent.parent.parent / "data" / "restricted_zones.json"
try:
    _ZONES: list[Zone] = add_bbox(json.loads(_ZONES_PATH.read_text()))
except (FileNotFoundError, json.JSONDecodeError) as _e:
    log.error("Failed to load restricted_zones.json: %s — zone speeding detection disabled", _e)
    _ZONES = []


def _trip_hash(trip_records: list) -> str:
    content = json.dumps(
        [{"t": r["timestamp"], "la": r["gps_lat"], "lo": r["gps_lon"], "s": r["speed"]} for r in trip_records]
    )
    return hashlib.sha256(content.encode()).hexdigest()


def _process_batch(records: list) -> None:
    cleaned = cleanse(records)
    trips = segment(cleaned)
    saved = 0

    db = SessionLocal()
    try:
        for trip_records in trips:
            if not trip_records:
                continue

            h = _trip_hash(trip_records)
            if db.execute(select(Trip).where(Trip.source_hash == h)).scalar_one_or_none() is not None:
                log.debug("Trip %s already exists, skipping", h[:8])
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

            try:
                db.commit()
                saved += 1
            except IntegrityError:
                db.rollback()
                log.debug("Trip %s race-condition duplicate, skipped", h[:8])

        log.info("Flushed %d records → %d/%d trips saved", len(records), saved, len(trips))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run() -> None:
    init_db()

    if not _ZONES:
        log.warning("No restricted zones loaded — zone speeding detection disabled")

    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP_SERVERS,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        group_id="pipeline-consumer",
    )

    buffer: list = []
    last_flush = time.time()

    log.info("Consumer started. Listening on '%s' (bootstrap: %s)...", TOPIC, BOOTSTRAP_SERVERS)

    while True:
        try:
            batch = consumer.poll(timeout_ms=1000)
        except Exception:
            log.exception("Kafka poll failed; retrying...")
            continue

        for messages in batch.values():
            for msg in messages:
                buffer.append(msg.value)

        size_exceeded = len(buffer) >= MAX_BUFFER_SIZE
        time_exceeded = buffer and time.time() - last_flush >= FLUSH_INTERVAL
        if size_exceeded or time_exceeded:
            log.info("Flushing %d buffered records...", len(buffer))
            try:
                _process_batch(buffer)
                consumer.commit()
            except Exception:
                log.exception("Batch processing failed; %d records dropped from buffer", len(buffer))
            finally:
                buffer = []
                last_flush = time.time()


if __name__ == "__main__":
    run()
