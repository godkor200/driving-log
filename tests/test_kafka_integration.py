"""
Kafka 통합 테스트 — 실제 Kafka broker가 필요하다.

실행 조건:
    docker compose up -d zookeeper kafka

Kafka가 localhost:9092에 없으면 모듈 전체를 자동 skip한다.
"""
import json
import time

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Event, Trip
from app.kafka import consumer as consumer_module

BOOTSTRAP = "localhost:9092"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def kafka_bootstrap():
    """Kafka 연결을 검증하고 없으면 모듈 전체를 skip."""
    from kafka import KafkaProducer
    try:
        p = KafkaProducer(bootstrap_servers=BOOTSTRAP, request_timeout_ms=3000)
        p.close()
    except Exception:
        pytest.skip("Kafka unavailable — docker compose up -d zookeeper kafka")
    return BOOTSTRAP


@pytest.fixture
def topic():
    """테스트별 고유 토픽 이름 — Kafka auto-create로 생성된다."""
    return f"test-driving-{time.time_ns()}"


@pytest.fixture
def db_session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


@pytest.fixture
def patched_consumer_db(db_session_factory, monkeypatch):
    """consumer 모듈의 SessionLocal을 테스트 전용 DB로 교체."""
    monkeypatch.setattr(consumer_module, "SessionLocal", db_session_factory)
    return db_session_factory


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_records(n: int, base_ts: int = 1_710_000_000) -> list[dict]:
    return [
        {
            "timestamp": base_ts + i,
            "gps_lat": 37.5 + i * 0.0001,
            "gps_lon": 127.0 + i * 0.0001,
            "speed": 30.0 + (i % 5),
        }
        for i in range(n)
    ]


def produce(bootstrap: str, topic: str, records: list[dict]) -> None:
    from kafka import KafkaProducer
    producer = KafkaProducer(
        bootstrap_servers=bootstrap,
        value_serializer=lambda v: json.dumps(v).encode(),
    )
    for r in records:
        producer.send(topic, r)
    producer.flush()
    producer.close()


def consume_all(bootstrap: str, topic: str, expected_count: int, timeout_sec: int = 10) -> list[dict]:
    from kafka import KafkaConsumer
    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=bootstrap,
        value_deserializer=lambda m: json.loads(m.decode()),
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        group_id=f"test-group-{time.time_ns()}",
        consumer_timeout_ms=timeout_sec * 1000,
    )
    buffer = []
    for msg in consumer:
        buffer.append(msg.value)
        if len(buffer) >= expected_count:
            break
    consumer.close()
    return buffer


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_records_flow_through_kafka(kafka_bootstrap, topic):
    """Produce 후 Consumer가 동일한 레코드를 모두 수신한다."""
    records = make_records(10)
    produce(kafka_bootstrap, topic, records)
    received = consume_all(kafka_bootstrap, topic, expected_count=10)

    assert len(received) == 10
    assert received[0]["timestamp"] == records[0]["timestamp"]


def test_pipeline_saves_trip_to_db(kafka_bootstrap, topic, patched_consumer_db):
    """Kafka에서 수신한 레코드를 _process_batch로 처리하면 Trip이 DB에 저장된다."""
    records = make_records(20)
    produce(kafka_bootstrap, topic, records)
    received = consume_all(kafka_bootstrap, topic, expected_count=20)

    assert len(received) == 20
    consumer_module._process_batch(received)

    with patched_consumer_db() as db:
        trips = db.execute(select(Trip)).scalars().all()

    assert len(trips) >= 1
    assert sum(t.record_count for t in trips) == len(records)


def test_pipeline_idempotent(kafka_bootstrap, topic, patched_consumer_db):
    """동일 레코드를 두 번 처리해도 Trip은 1개만 저장된다."""
    records = make_records(15)
    produce(kafka_bootstrap, topic, records)
    received = consume_all(kafka_bootstrap, topic, expected_count=15)

    consumer_module._process_batch(received)
    consumer_module._process_batch(received)  # 재처리

    with patched_consumer_db() as db:
        trips = db.execute(select(Trip)).scalars().all()

    assert len(trips) == 1


def test_pipeline_detects_sudden_accel(kafka_bootstrap, topic, patched_consumer_db):
    """급가속 레코드가 포함된 배치를 처리하면 SUDDEN_ACCEL 이벤트가 탐지된다."""
    records = make_records(10, base_ts=1_710_010_000)
    records[5]["speed"] = 80.0  # 이전 속도 34.0 → 1초에 46 km/h 급등

    produce(kafka_bootstrap, topic, records)
    received = consume_all(kafka_bootstrap, topic, expected_count=10)
    consumer_module._process_batch(received)

    with patched_consumer_db() as db:
        events = db.execute(select(Event)).scalars().all()

    assert any(e.event_type == "SUDDEN_ACCEL" for e in events)


def test_pipeline_handles_gps_jump(kafka_bootstrap, topic, patched_consumer_db):
    """GPS 점프가 있는 레코드도 크래시 없이 처리되고 Trip이 저장된다."""
    records = make_records(10, base_ts=1_710_020_000)
    records[3]["gps_lat"] = 35.0   # 300km/h 초과 이동 → cleansing에서 None 처리 후 보간
    records[3]["gps_lon"] = 129.0

    produce(kafka_bootstrap, topic, records)
    received = consume_all(kafka_bootstrap, topic, expected_count=10)
    consumer_module._process_batch(received)

    with patched_consumer_db() as db:
        trips = db.execute(select(Trip)).scalars().all()

    assert len(trips) >= 1
