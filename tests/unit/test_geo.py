import numpy as np
import pytest

from app.domain.pipeline.geo import haversine_m, haversine_m_bruteforce


def test_haversine_known_distance() -> None:
    # 서울 시청(37.5665, 126.9780) ~ 광화문(37.5759, 126.9769), 약 1050m
    lat1 = np.array([37.5665])
    lon1 = np.array([126.9780])
    lat2 = np.array([37.5759])
    lon2 = np.array([126.9769])
    dist = haversine_m(lat1, lon1, lat2, lon2)
    assert dist == pytest.approx(1050.0, rel=0.05)


def test_haversine_matches_bruteforce() -> None:
    # 벡터 연산 결과와 브루트포스 결과가 완전히 일치해야 한다
    rng = np.random.default_rng(42)
    lats1 = rng.uniform(33.0, 39.0, 100)
    lons1 = rng.uniform(124.0, 132.0, 100)
    lats2 = rng.uniform(33.0, 39.0, 100)
    lons2 = rng.uniform(124.0, 132.0, 100)

    vectorized = haversine_m(lats1, lons1, lats2, lons2)
    bruteforce = np.array(
        [haversine_m_bruteforce(lats1[i], lons1[i], lats2[i], lons2[i]) for i in range(100)]
    )
    np.testing.assert_allclose(vectorized, bruteforce, rtol=1e-10)
