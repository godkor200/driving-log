import pytest
from app.pipeline.cleansing import cleanse, MAX_SPEED


def test_sort_by_timestamp():
    """timestamp 기준 정렬 확인"""
    records = [
        {"timestamp": 3, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 10.0},
        {"timestamp": 1, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 10.0},
        {"timestamp": 2, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 10.0},
    ]
    result = cleanse(records)
    assert [r["timestamp"] for r in result] == [1, 2, 3]


def test_interpolate_missing_speed():
    """속도 결측값 선형 보간 확인"""
    records = [
        {"timestamp": 1, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 0.0},
        {"timestamp": 2, "gps_lat": 37.5, "gps_lon": 127.0, "speed": None},
        {"timestamp": 3, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 20.0},
    ]
    result = cleanse(records)
    assert result[1]["speed"] == pytest.approx(10.0)


def test_interpolate_missing_gps():
    """GPS 결측값 선형 보간 확인"""
    records = [
        {"timestamp": 1, "gps_lat": 37.0, "gps_lon": 127.0, "speed": 10.0},
        {"timestamp": 2, "gps_lat": None, "gps_lon": None,   "speed": 10.0},
        {"timestamp": 3, "gps_lat": 38.0, "gps_lon": 128.0, "speed": 10.0},
    ]
    result = cleanse(records)
    assert result[1]["gps_lat"] == pytest.approx(37.5)
    assert result[1]["gps_lon"] == pytest.approx(127.5)


def test_speed_outlier_interpolated():
    """MAX_SPEED 초과 속도가 보간되는지 확인"""
    records = [
        {"timestamp": 1, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 0.0},
        {"timestamp": 2, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 221.74},
        {"timestamp": 3, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 0.0},
    ]
    result = cleanse(records)
    assert result[1]["speed"] <= MAX_SPEED


def test_empty_input():
    """빈 입력 처리 확인"""
    assert cleanse([]) == []


def test_negative_speed_interpolated():
    """음수 속도(물리적으로 불가능)는 이상치로 처리되어 보간된다"""
    records = [
        {"timestamp": 1, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 0.0},
        {"timestamp": 2, "gps_lat": 37.5, "gps_lon": 127.0, "speed": -10.0},
        {"timestamp": 3, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 0.0},
    ]
    result = cleanse(records)
    assert result[1]["speed"] >= 0


def test_normal_records_unchanged():
    """정상 레코드는 변경되지 않아야 함"""
    records = [
        {"timestamp": 1, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 30.0},
        {"timestamp": 2, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 50.0},
    ]
    result = cleanse(records)
    assert result[0]["speed"] == 30.0
    assert result[1]["speed"] == 50.0


def test_speed_boundary_not_outlier():
    """경계값 0.0과 MAX_SPEED(150.0)는 이상치가 아니므로 보간되지 않는다"""
    records = [
        {"timestamp": 1, "gps_lat": 37.5, "gps_lon": 127.0, "speed": 0.0},
        {"timestamp": 2, "gps_lat": 37.5, "gps_lon": 127.0, "speed": MAX_SPEED},
    ]
    result = cleanse(records)
    assert result[0]["speed"] == 0.0
    assert result[1]["speed"] == MAX_SPEED


def test_all_speed_none_unchanged():
    """모든 speed가 None이면 보간 불가 — 레코드 수만 유지된다"""
    records = [
        {"timestamp": 1, "gps_lat": 37.5, "gps_lon": 127.0, "speed": None},
        {"timestamp": 2, "gps_lat": 37.5, "gps_lon": 127.0, "speed": None},
    ]
    result = cleanse(records)
    assert len(result) == 2
