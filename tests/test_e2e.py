from unittest.mock import patch

from fastapi.testclient import TestClient


def test_analyze_returns_trips(analyze_result):
    """실제 데이터로 분석 수행 시 Trip이 1개 이상 반환된다"""
    assert analyze_result["trip_count"] >= 1
    assert len(analyze_result["trips"]) == analyze_result["trip_count"]


def test_get_trip_returns_detail(client: TestClient, analyze_result):
    """analyze 후 반환된 trip_id로 상세 조회가 가능하다"""
    trip_id = analyze_result["trips"][0]["trip_id"]
    response = client.get(f"/trips/{trip_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == trip_id
    assert body["distance_km"] > 0
    assert body["duration_seconds"] >= 0
    assert isinstance(body["events"], list)


def test_get_trip_has_events(analyze_result):
    """실제 데이터에서 위험 운전 이벤트가 1건 이상 탐지된다"""
    total_events = sum(t["event_count"] for t in analyze_result["trips"])
    assert total_events >= 1


def test_speeding_school_zone_detected(client: TestClient, analyze_result):
    """실제 데이터에서 SPEEDING_RESTRICTED_ZONE 이벤트가 end-to-end로 탐지된다"""
    trip_ids = [t["trip_id"] for t in analyze_result["trips"]]
    all_events = []
    for trip_id in trip_ids:
        body = client.get(f"/trips/{trip_id}").json()
        all_events.extend(body["events"])

    event_types = {e["event_type"] for e in all_events}
    assert "SPEEDING_RESTRICTED_ZONE" in event_types


def test_get_trip_not_found(client: TestClient):
    """존재하지 않는 trip_id는 404를 반환한다"""
    response = client.get("/trips/999999")
    assert response.status_code == 404


def test_analyze_empty_records(client: TestClient):
    """빈 records 배열은 trip_count 0을 반환한다"""
    response = client.post("/analyze", json={"records": []})
    assert response.status_code == 200
    body = response.json()
    assert body["trip_count"] == 0
    assert body["trips"] == []


def test_analyze_returns_500_when_zones_not_loaded(client: TestClient):
    """school_zones.json 로드 실패 시 /analyze는 500을 반환한다"""
    with patch("app.api.routes._ZONES_LOADED", False):
        response = client.post("/analyze", json={"records": []})
    assert response.status_code == 500


def test_analyze_too_many_records_returns_413(client: TestClient):
    """MAX_RECORDS 초과 시 413을 반환한다"""
    with patch("app.api.routes.MAX_RECORDS", 2):
        records = [{"timestamp": i + 1, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 20.0}
                   for i in range(3)]
        response = client.post("/analyze", json={"records": records})
    assert response.status_code == 413


def test_invalid_gps_lat_returns_422(client: TestClient):
    """gps_lat 범위(-90~90) 초과 시 422를 반환한다"""
    records = [{"timestamp": 1, "gps_lat": 91.0, "gps_lon": 127.0, "speed": 20.0}]
    response = client.post("/analyze", json={"records": records})
    assert response.status_code == 422


def test_invalid_timestamp_returns_422(client: TestClient):
    """timestamp <= 0 시 422를 반환한다"""
    records = [{"timestamp": -1, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 20.0}]
    response = client.post("/analyze", json={"records": records})
    assert response.status_code == 422


def test_analyze_idempotent(client: TestClient):
    """같은 records를 두 번 POST하면 동일한 trip_id를 반환한다"""
    records = [
        {"timestamp": 1000, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 20.0},
        {"timestamp": 1001, "gps_lat": 37.5001, "gps_lon": 127.0001, "speed": 21.0},
    ]
    r1 = client.post("/analyze", json={"records": records})
    r2 = client.post("/analyze", json={"records": records})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["trips"][0]["trip_id"] == r2.json()["trips"][0]["trip_id"]
