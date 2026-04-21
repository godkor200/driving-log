"""
driving_log.json을 읽어 Kafka driving-logs 토픽으로 전송하는 시뮬레이터.

실행:
    python scripts/produce_logs.py

환경변수:
    KAFKA_BOOTSTRAP_SERVERS  기본값: localhost:9092
    KAFKA_TOPIC              기본값: driving-logs
    PRODUCE_DELAY_MS         레코드 간 지연(ms), 기본값: 10
"""
import json
import os
import time
from pathlib import Path

from kafka import KafkaProducer

BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(",")
TOPIC = os.getenv("KAFKA_TOPIC", "driving-logs")
DELAY_MS = float(os.getenv("PRODUCE_DELAY_MS", "10"))

producer = KafkaProducer(
    bootstrap_servers=BOOTSTRAP_SERVERS,
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
)

data_path = Path(__file__).parent.parent / "data" / "driving_log.json"
records = json.loads(data_path.read_text())

print(f"Sending {len(records)} records to topic '{TOPIC}'...")

for i, record in enumerate(records, 1):
    producer.send(TOPIC, record)
    if DELAY_MS > 0:
        time.sleep(DELAY_MS / 1000)
    if i % 500 == 0:
        print(f"  {i}/{len(records)} sent")

producer.flush()
print(f"Done. {len(records)} records sent.")
