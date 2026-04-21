from app.pipeline.detection import detect, SUDDEN_CHANGE_THRESHOLD, RESTRICTED_ZONE_SPEED_LIMIT
from app.utils.geo import add_bbox


def make_record(timestamp, speed, lat=37.5, lon=127.0):
    return {"timestamp": timestamp, "speed": speed, "gps_lat": lat, "gps_lon": lon}


def make_zone(lat, lon, radius=300, name="테스트구역"):
    return add_bbox([{"name": name, "gps_lat": lat, "gps_lon": lon, "radius_meters": radius}])[0]


# ── 시간 정규화 (rate = delta / time_gap) ────────────────────

def test_sudden_accel_time_normalized():
    """
    3초 간격으로 12km/h 증가 → 변화율 4km/h/s
    절대값(12) 기준이면 탐지, 시간 정규화(4km/h/s) 기준이면 탐지 안 됨
    스펙: '1초 단위 시간 변화량 대비 10km/h 이상'
    """
    trip = [
        make_record(timestamp=0, speed=20.0),
        make_record(timestamp=3, speed=32.0),  # delta=12, rate=4km/h/s
    ]
    events = detect(trip, zones=[])
    assert len(events) == 0  # 4km/h/s < 10km/h/s → 탐지 안 됨


def test_sudden_accel_1sec_gap():
    """1초 간격 10km/h 증가 → 변화율 10km/h/s → 탐지"""
    trip = [
        make_record(timestamp=0, speed=20.0),
        make_record(timestamp=1, speed=30.0),  # rate=10km/h/s
    ]
    events = detect(trip, zones=[])
    assert len(events) == 1
    assert events[0]["event_type"] == "SUDDEN_ACCEL"


# ── 급가속/급감속 ──────────────────────────────────────────

def test_sudden_accel_detected():
    """속도가 10km/h 이상 증가하면 SUDDEN_ACCEL 탐지"""
    trip = [
        make_record(1, 20.0),
        make_record(2, 20.0 + SUDDEN_CHANGE_THRESHOLD),
    ]
    events = detect(trip, zones=[])
    assert len(events) == 1
    assert events[0]["event_type"] == "SUDDEN_ACCEL"


def test_sudden_decel_detected():
    """속도가 10km/h 이상 감소하면 SUDDEN_DECEL 탐지"""
    trip = [
        make_record(1, 40.0),
        make_record(2, 40.0 - SUDDEN_CHANGE_THRESHOLD),
    ]
    events = detect(trip, zones=[])
    assert len(events) == 1
    assert events[0]["event_type"] == "SUDDEN_DECEL"


def test_no_event_below_threshold():
    """변화량이 threshold 미만이면 이벤트 없음"""
    trip = [
        make_record(1, 20.0),
        make_record(2, 20.0 + SUDDEN_CHANGE_THRESHOLD - 0.1),
    ]
    events = detect(trip, zones=[])
    assert len(events) == 0


def test_single_record_no_event():
    """레코드 1개면 비교 대상 없어서 이벤트 없음"""
    events = detect([make_record(1, 50.0)], zones=[])
    assert len(events) == 0


def test_empty_trip_no_event():
    """빈 Trip은 이벤트 없음"""
    assert detect([], zones=[]) == []


# ── 제한구역 과속 ──────────────────────────────────────────

def test_school_zone_speeding_detected():
    """제한구역 반경 내에서 제한속도 초과 시 SPEEDING_RESTRICTED_ZONE 탐지"""
    trip = [make_record(1, RESTRICTED_ZONE_SPEED_LIMIT + 1.0, lat=37.5, lon=127.0)]
    zones = [make_zone(lat=37.5, lon=127.0, radius=300)]
    events = detect(trip, zones=zones)
    assert len(events) == 1
    assert events[0]["event_type"] == "SPEEDING_RESTRICTED_ZONE"


def test_school_zone_no_speeding():
    """제한구역 반경 내에서 제한속도 이하면 이벤트 없음"""
    trip = [make_record(1, RESTRICTED_ZONE_SPEED_LIMIT, lat=37.5, lon=127.0)]
    zones = [make_zone(lat=37.5, lon=127.0, radius=300)]
    events = detect(trip, zones=zones)
    assert len(events) == 0


def test_school_zone_outside_radius():
    """제한구역 반경 밖이면 이벤트 없음"""
    trip = [make_record(1, 50.0, lat=37.5, lon=127.0)]
    zones = [make_zone(lat=38.0, lon=128.0, radius=300)]  # 멀리 떨어진 zone
    events = detect(trip, zones=zones)
    assert len(events) == 0


def test_school_zone_one_event_per_record():
    """여러 zone에 걸쳐도 레코드당 이벤트는 1개"""
    trip = [make_record(1, 50.0, lat=37.5, lon=127.0)]
    zones = [
        make_zone(lat=37.5, lon=127.0, radius=300, name="zone1"),
        make_zone(lat=37.5, lon=127.0, radius=300, name="zone2"),
    ]
    events = detect(trip, zones=zones)
    assert len(events) == 1


def test_school_zone_skips_none_gps():
    """GPS가 None인 레코드는 제한구역 비교 대상에서 제외된다"""
    trip = [{"timestamp": 1, "speed": 50.0, "gps_lat": None, "gps_lon": None}]
    zones = [make_zone(lat=37.5, lon=127.0, radius=300)]
    events = detect(trip, zones=zones)
    assert len(events) == 0


def test_same_timestamp_no_accel_event():
    """동일 timestamp 연속 레코드는 time_gap=0 → 이벤트 없음"""
    trip = [
        make_record(timestamp=1, speed=20.0),
        make_record(timestamp=1, speed=100.0),  # gap=0, rate 계산 불가
    ]
    events = detect(trip, zones=[])
    assert len(events) == 0
