import hashlib

from perp_mm_funding.build_replication_manifest import describe_file


def test_describe_file_records_sha256(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_bytes(b"replication")

    result = describe_file(path)

    assert result["status"] == "available"
    assert result["sha256"] == hashlib.sha256(b"replication").hexdigest()


def test_describe_file_marks_missing_input(tmp_path):
    result = describe_file(tmp_path / "missing.parquet")

    assert result["status"] == "missing"
