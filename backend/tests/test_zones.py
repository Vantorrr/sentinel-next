"""Zone tracker unit tests — pure logic, no DB needed."""

import pytest
from sentinel.services.ai.zone_tracker import _point_in_polygon


def test_point_inside_square():
    poly = [(0, 0), (100, 0), (100, 100), (0, 100)]
    assert _point_in_polygon(50, 50, poly) is True


def test_point_outside_square():
    poly = [(0, 0), (100, 0), (100, 100), (0, 100)]
    assert _point_in_polygon(150, 50, poly) is False
    assert _point_in_polygon(-10, 50, poly) is False
    assert _point_in_polygon(50, -10, poly) is False
    assert _point_in_polygon(50, 150, poly) is False


def test_point_inside_triangle():
    poly = [(50, 0), (100, 100), (0, 100)]
    assert _point_in_polygon(50, 50, poly) is True


def test_point_outside_triangle():
    poly = [(50, 0), (100, 100), (0, 100)]
    assert _point_in_polygon(5, 5, poly) is False
    assert _point_in_polygon(95, 5, poly) is False


def test_point_inside_irregular_polygon():
    poly = [(10, 10), (90, 10), (90, 50), (50, 90), (10, 50)]
    assert _point_in_polygon(50, 30, poly) is True
    assert _point_in_polygon(200, 200, poly) is False
