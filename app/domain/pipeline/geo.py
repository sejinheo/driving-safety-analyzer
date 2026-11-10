import math

import numpy as np
import numpy.typing as npt

_EARTH_RADIUS_M: float = 6_371_000.0


def haversine_m(
    lat1: npt.NDArray[np.float64],
    lon1: npt.NDArray[np.float64],
    lat2: npt.NDArray[np.float64],
    lon2: npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    """두 좌표 배열 사이의 Haversine 거리(미터)를 반환한다. 브로드캐스팅 지원."""
    lat1_r = np.radians(lat1)
    lat2_r = np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)

    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2) ** 2
    return _EARTH_RADIUS_M * 2 * np.arcsin(np.sqrt(a))


def haversine_m_bruteforce(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """검증용 순수 Python Haversine 거리(미터). 테스트에서 벡터 연산 결과와 비교한다."""
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return _EARTH_RADIUS_M * 2 * math.asin(math.sqrt(a))
