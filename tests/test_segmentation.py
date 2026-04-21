from app.pipeline.segmentation import segment, calc_distance_km, GAP_THRESHOLD


def make_record(timestamp, lat=37.5, lon=127.0):
    return {"timestamp": timestamp, "gps_lat": lat, "gps_lon": lon, "speed": 30.0}


def test_single_trip():
    """공백 없는 연속 데이터는 Trip 1개"""
    records = [make_record(i) for i in range(1, 10)]
    result = segment(records)
    assert len(result) == 1
    assert len(result[0]) == 9


def test_split_on_gap():
    """GAP_THRESHOLD 이상 공백이면 Trip 2개로 분리"""
    records = [
        make_record(1),
        make_record(2),
        make_record(2 + GAP_THRESHOLD),
        make_record(2 + GAP_THRESHOLD + 1),
    ]
    result = segment(records)
    assert len(result) == 2
    assert len(result[0]) == 2
    assert len(result[1]) == 2


def test_gap_just_below_threshold():
    """GAP_THRESHOLD - 1 공백은 분리하지 않음"""
    records = [
        make_record(1),
        make_record(1 + GAP_THRESHOLD - 1),
    ]
    result = segment(records)
    assert len(result) == 1


def test_empty_input():
    """빈 입력은 빈 리스트 반환"""
    assert segment([]) == []


def test_single_record():
    """레코드 1개는 Trip 1개"""
    result = segment([make_record(1)])
    assert len(result) == 1
    assert len(result[0]) == 1


def test_multiple_gaps():
    """공백이 여러 개면 Trip도 여러 개"""
    records = [
        make_record(1),
        make_record(1 + GAP_THRESHOLD),
        make_record(1 + GAP_THRESHOLD * 2),
    ]
    result = segment(records)
    assert len(result) == 3


def test_calc_distance_same_point():
    """같은 위치만 있으면 거리 0"""
    records = [make_record(i) for i in range(3)]
    assert calc_distance_km(records) == 0.0


def test_calc_distance_known():
    """서울 → 수원 직선 거리 약 27km"""
    records = [
        {"timestamp": 1, "gps_lat": 37.5665, "gps_lon": 126.9780, "speed": 0.0},  # 서울
        {"timestamp": 2, "gps_lat": 37.2636, "gps_lon": 127.0286, "speed": 0.0},  # 수원
    ]
    dist = calc_distance_km(records)
    assert 25.0 < dist < 35.0


def test_calc_distance_single_record():
    """레코드 1개는 거리 계산 불가 → 0.0"""
    assert calc_distance_km([make_record(1)]) == 0.0


def test_calc_distance_all_none_gps():
    """GPS가 전부 None이면 거리 0.0"""
    records = [
        {"timestamp": 1, "gps_lat": None, "gps_lon": None, "speed": 0.0},
        {"timestamp": 2, "gps_lat": None, "gps_lon": None, "speed": 0.0},
    ]
    assert calc_distance_km(records) == 0.0


def test_calc_distance_skips_none_gps():
    """GPS 누락 레코드는 건너뛰고 계산 가능한 구간만 합산"""
    records = [
        {"timestamp": 1, "gps_lat": 37.5665, "gps_lon": 126.9780, "speed": 0.0},
        {"timestamp": 2, "gps_lat": None, "gps_lon": None, "speed": 0.0},
        {"timestamp": 3, "gps_lat": 37.5665, "gps_lon": 126.9780, "speed": 0.0},
    ]
    assert calc_distance_km(records) == 0.0
