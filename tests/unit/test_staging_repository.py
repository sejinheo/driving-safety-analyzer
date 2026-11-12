"""iter_analyze_chunks 키셋 페이지네이션 엣지케이스 테스트."""

from unittest.mock import MagicMock

from app.infra.persistence.staging_repository import iter_analyze_chunks

_SCHEMA_KEYS = [
    "vehicle_id",
    "ts",
    "source_index",
    "lat",
    "lon",
    "speed",
    "speed_invalid",
    "speed_out_of_range",
    "gps_swapped",
    "gps_invalid",
]


def _row(vehicle_id: str, ts: int, source_index: int) -> tuple[object, ...]:
    return (vehicle_id, ts, source_index, 37.5, 127.0, 60.0, False, False, False, False)


def _mock_conn(pages: list[list[tuple[object, ...]]]) -> MagicMock:
    """pages: 호출할 때마다 순서대로 반환할 행 목록. 마지막 빈 결과는 자동 추가."""
    conn = MagicMock()
    results = [MagicMock(fetchall=MagicMock(return_value=p)) for p in pages] + [
        MagicMock(fetchall=MagicMock(return_value=[]))
    ]
    conn.execute.side_effect = results
    return conn


def _chunks(conn: MagicMock, *, chunk_size: int = 100) -> list[object]:
    return list(
        iter_analyze_chunks(
            conn,
            run_id=1,
            last_vehicle="",
            last_ts=0,
            last_source_index=0,
            chunk_size=chunk_size,
        )
    )


def test_all_rows_returned_no_duplicates() -> None:
    """중복 없는 단순 케이스: 모든 행이 반환된다."""
    rows = [_row("V1", 1000, 0), _row("V1", 1001, 1), _row("V1", 1002, 2)]
    conn = _mock_conn([rows])

    chunks = _chunks(conn)

    assert len(chunks) == 1
    assert len(chunks[0]) == 3


def test_duplicate_ts_across_chunk_boundary_no_data_loss() -> None:
    """핵심 버그 케이스: 같은 (vehicle_id, ts)가 청크 경계에 걸려도 데이터 유실 없음.

    chunk_size=2일 때:
    - 1차 조회: (V1,1000,0), (V1,1000,1) → last_source_index=1
    - 2차 조회: (V1,1000,1) 초과이므로 (V1,1000,2) 반환
    - 3차 조회: 빈 결과 → 종료
    """
    page1 = [_row("V1", 1000, 0), _row("V1", 1000, 1)]
    page2 = [_row("V1", 1000, 2)]
    conn = _mock_conn([page1, page2])

    chunks = _chunks(conn, chunk_size=2)

    total_rows = sum(len(c) for c in chunks)
    assert total_rows == 3, f"expected 3 rows, got {total_rows}"


def test_cursor_advances_correctly_across_chunks() -> None:
    """커서 (last_vehicle, last_ts, last_source_index)가 청크마다 올바르게 전진한다."""
    page1 = [_row("A", 100, 0), _row("A", 200, 1)]
    page2 = [_row("B", 100, 2), _row("B", 200, 3)]
    conn = _mock_conn([page1, page2])

    _chunks(conn, chunk_size=2)

    second_call_params = conn.execute.call_args_list[1][0][1]
    assert second_call_params["last_vehicle"] == "A"
    assert second_call_params["last_ts"] == 200
    assert second_call_params["last_source_index"] == 1


def test_empty_table_returns_no_chunks() -> None:
    """빈 테이블: 청크 없음."""
    conn = _mock_conn([[]])

    assert _chunks(conn) == []


def test_single_row_returns_one_chunk() -> None:
    """행이 1개: 청크 1개, 행 1개."""
    conn = _mock_conn([[_row("V1", 1000, 0)]])

    chunks = _chunks(conn)

    assert len(chunks) == 1
    assert len(chunks[0]) == 1


def test_stops_when_rows_less_than_chunk_size() -> None:
    """마지막 청크가 chunk_size보다 작으면 추가 쿼리 없이 종료한다."""
    rows = [_row("V1", 1000, i) for i in range(3)]
    conn = _mock_conn([rows])

    _chunks(conn, chunk_size=10)

    # 3행 < chunk_size=10 이므로 쿼리 1번만 실행
    assert conn.execute.call_count == 1


def test_resume_from_checkpoint() -> None:
    """체크포인트에서 재개: last_source_index 이후부터 조회한다."""
    rows = [_row("V1", 2000, 50), _row("V1", 2001, 51)]
    conn = _mock_conn([rows])

    list(
        iter_analyze_chunks(
            conn,
            run_id=1,
            last_vehicle="V1",
            last_ts=1999,
            last_source_index=49,
            chunk_size=100,
        )
    )

    first_call_params = conn.execute.call_args_list[0][0][1]
    assert first_call_params["last_vehicle"] == "V1"
    assert first_call_params["last_ts"] == 1999
    assert first_call_params["last_source_index"] == 49


def test_all_same_ts_across_multiple_chunks() -> None:
    """모든 행이 같은 ts: chunk_size=2로 나눠도 전체 행 수 보존."""
    all_rows = [_row("V1", 1000, i) for i in range(5)]
    conn = _mock_conn([all_rows[:2], all_rows[2:4], all_rows[4:]])

    chunks = _chunks(conn, chunk_size=2)

    assert sum(len(c) for c in chunks) == 5
