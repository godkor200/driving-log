import pytest
from app.utils.geo import add_bbox


def test_add_bbox_adds_fields():
    """add_bbox 후 bounding box 필드가 추가된다"""
    zones = [{"name": "테스트", "gps_lat": 37.5, "gps_lon": 127.0, "radius_meters": 111_000}]
    result = add_bbox(zones)
    assert "_lat_min" in result[0]
    assert "_lat_max" in result[0]
    assert "_lon_min" in result[0]
    assert "_lon_max" in result[0]


def test_add_bbox_correct_lat_range():
    """radius_meters=111_000 이면 lat 범위가 약 ±1도"""
    zones = [{"name": "테스트", "gps_lat": 37.5, "gps_lon": 127.0, "radius_meters": 111_000}]
    result = add_bbox(zones)[0]
    assert result["_lat_min"] == pytest.approx(36.5, abs=0.01)
    assert result["_lat_max"] == pytest.approx(38.5, abs=0.01)


def test_add_bbox_point_inside():
    """반경 내 좌표는 bounding box 안에 있다"""
    zones = [{"name": "테스트", "gps_lat": 37.5, "gps_lon": 127.0, "radius_meters": 300}]
    result = add_bbox(zones)[0]
    assert result["_lat_min"] <= 37.5 <= result["_lat_max"]
    assert result["_lon_min"] <= 127.0 <= result["_lon_max"]


def test_add_bbox_empty():
    """빈 리스트 입력은 빈 리스트 반환"""
    assert add_bbox([]) == []
