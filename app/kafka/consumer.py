"""
Kafka consumer — driving-logs 토픽을 구독하여 파이프라인을 실행하고 DB에 적재한다.

수신된 레코드는 FLUSH_INTERVAL(초) 단위로 버퍼링 후 일괄 처리한다.
cleansing/segmentation이 레코드 시퀀스 전체를 필요로 하기 때문에
단건 처리가 아닌 시간 윈도우 기반 배치 처리를 택했다.
"""
import json
import logging
import os
import time
from pathlib import Path

from kafka import KafkaConsumer
from sqlalchemy import insert

from app.db.models import DrivingLog, Event, Trip
from app.db.session import SessionLocal, init_db
from app.pipeline.cleansing import cleanse
from app.pipeline.detection import detect
from app.pipeline.segmentation import calc_distance_km, segment
from app.types import Zone
from app.utils.geo import add_bbox

TOPIC = os.getenv("KAFKA_TOPIC", "driving-logs")
BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")
FLUSH_INTERVAL = int(os.getenv("FLUSH_INTERVAL", "10"))  # seconds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_ZONES_PATH = Path(__file__).parent.parent.parent / "data" / "restricted_zones.json"
_ZONES: list[Zone] = add_bbox(json.loads(_ZONES_PATH.read_text()))


def _process_batch(records: list) -> None:
    cleaned = cleanse(records)
    trips = segment(cleaned)

    db = SessionLocal()
    try:
        for trip_records in trips:
            if not trip_records:
                continue

            distance_km = calc_distance_km(trip_records)
            events = detect(trip_records, _ZONES)

            trip = Trip(
                start_time=trip_records[0]["timestamp"],
                end_time=trip_records[-1]["timestamp"],
                distance_km=distance_km,
                record_count=len(trip_records),
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

        db.commit()
        log.info("Flushed %d records → %d trips saved", len(records), len(trips))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run() -> None:
    init_db()
    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP_SERVERS,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="earliest",
        group_id="pipeline-consumer",
    )

    buffer: list = []
    last_flush = time.time()

    log.info("Consumer started. Listening on '%s' (bootstrap: %s)...", TOPIC, BOOTSTRAP_SERVERS)

    while True:
        batch = consumer.poll(timeout_ms=1000)
        for messages in batch.values():
            for msg in messages:
                buffer.append(msg.value)

        if buffer and time.time() - last_flush >= FLUSH_INTERVAL:
            log.info("Flushing %d buffered records...", len(buffer))
            _process_batch(buffer)
            buffer = []
            last_flush = time.time()


if __name__ == "__main__":
    run()
