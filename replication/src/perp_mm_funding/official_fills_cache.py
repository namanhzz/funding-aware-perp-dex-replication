from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import boto3
import pandas as pd
import typer
from botocore.config import Config
from botocore.exceptions import ClientError

from perp_mm_funding.io import ensure_parent, write_parquet
from perp_mm_funding.s3_fills import HYPERLIQUID_NODE_DATA_BUCKET, hourly_fill_key, local_hourly_path


app = typer.Typer(help="Cache official Hyperliquid S3 node_fills_by_block hourly files.")


@dataclass(frozen=True, slots=True)
class FillObject:
    date: str
    hour: int
    raw_dir: Path

    @property
    def key(self) -> str:
        return hourly_fill_key(datetime.strptime(self.date, "%Y%m%d").date(), self.hour)

    @property
    def s3_uri(self) -> str:
        return f"s3://{HYPERLIQUID_NODE_DATA_BUCKET}/{self.key}"

    @property
    def local_path(self) -> Path:
        return local_hourly_path(self.raw_dir, datetime.strptime(self.date, "%Y%m%d").date(), self.hour)


def _normalize_date(value: str) -> str:
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    raise typer.BadParameter(f"Invalid date {value!r}; expected YYYYMMDD or YYYY-MM-DD")


def _iter_dates(start_date: str, end_date: str) -> Iterable[str]:
    start = datetime.strptime(_normalize_date(start_date), "%Y%m%d")
    end = datetime.strptime(_normalize_date(end_date), "%Y%m%d")
    if end < start:
        raise typer.BadParameter("end_date must be on or after start_date")
    current = start
    while current <= end:
        yield current.strftime("%Y%m%d")
        current += timedelta(days=1)


def _parse_hours(value: str) -> list[int]:
    hours: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = [int(item) for item in part.split("-", 1)]
            hours.update(range(start, end + 1))
        else:
            hours.add(int(part))
    if not hours or any(hour < 0 or hour > 23 for hour in hours):
        raise typer.BadParameter("hours must contain values in 0..23")
    return sorted(hours)


def build_objects(start_date: str, end_date: str, hours: str, raw_dir: Path) -> list[FillObject]:
    return [
        FillObject(date=date, hour=hour, raw_dir=raw_dir)
        for date in _iter_dates(start_date, end_date)
        for hour in _parse_hours(hours)
    ]


def _s3_client(max_pool_connections: int):
    return boto3.client(
        "s3",
        config=Config(
            retries={"max_attempts": 8, "mode": "adaptive"},
            max_pool_connections=max_pool_connections,
        ),
    )


def _head_object(item: FillObject, max_pool_connections: int) -> dict[str, object]:
    local_path = item.local_path
    local_exists = local_path.exists()
    local_size = local_path.stat().st_size if local_exists else 0
    row = {
        "date": item.date,
        "hour": item.hour,
        "s3_uri": item.s3_uri,
        "s3_key": item.key,
        "local_path": str(local_path),
        "s3_exists": False,
        "s3_size_bytes": 0,
        "local_exists": local_exists,
        "local_size_bytes": local_size,
        "size_matches": False,
        "downloaded": False,
        "status": "unknown",
        "error": "",
    }
    try:
        response = _s3_client(max_pool_connections).head_object(
            Bucket=HYPERLIQUID_NODE_DATA_BUCKET,
            Key=item.key,
            RequestPayer="requester",
        )
        s3_size = int(response["ContentLength"])
        row.update(
            {
                "s3_exists": True,
                "s3_size_bytes": s3_size,
                "size_matches": local_exists and local_size == s3_size,
                "status": "cached" if local_exists and local_size == s3_size else "available",
            }
        )
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        row.update({"status": "missing" if code in {"404", "NoSuchKey", "NotFound"} else "head_failed", "error": code})
    except Exception as exc:
        row.update({"status": "head_failed", "error": type(exc).__name__})
    return row


def _download_object(item: FillObject, s3_size: int, overwrite: bool, max_pool_connections: int) -> dict[str, object]:
    local_path = item.local_path
    local_exists = local_path.exists()
    local_size = local_path.stat().st_size if local_exists else 0
    if local_exists and local_size == s3_size and not overwrite:
        return {
            "date": item.date,
            "hour": item.hour,
            "downloaded": False,
            "local_exists": True,
            "local_size_bytes": local_size,
            "size_matches": True,
            "status": "cached",
            "error": "",
        }

    ensure_parent(local_path)
    temp_path = local_path.with_name(f"{local_path.name}.part.{time.time_ns()}")
    try:
        _s3_client(max_pool_connections).download_file(
            HYPERLIQUID_NODE_DATA_BUCKET,
            item.key,
            str(temp_path),
            ExtraArgs={"RequestPayer": "requester"},
        )
        downloaded_size = temp_path.stat().st_size
        temp_path.replace(local_path)
        return {
            "date": item.date,
            "hour": item.hour,
            "downloaded": True,
            "local_exists": True,
            "local_size_bytes": downloaded_size,
            "size_matches": downloaded_size == s3_size,
            "status": "downloaded" if downloaded_size == s3_size else "size_mismatch",
            "error": "",
        }
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        return {
            "date": item.date,
            "hour": item.hour,
            "downloaded": False,
            "local_exists": local_path.exists(),
            "local_size_bytes": local_path.stat().st_size if local_path.exists() else 0,
            "size_matches": False,
            "status": "download_failed",
            "error": type(exc).__name__,
        }


def write_cache_report(manifest: pd.DataFrame, out: Path) -> None:
    total = len(manifest)
    s3_available = int(manifest["s3_exists"].sum())
    cached = int((manifest["local_exists"] & manifest["size_matches"]).sum())
    missing = int((~manifest["s3_exists"]).sum())
    downloaded = int(manifest["downloaded"].sum()) if "downloaded" in manifest.columns else 0
    lines = [
        "# Official Hyperliquid Fill Cache",
        "",
        "## Scope",
        "",
        "- source: official Hyperliquid requester-pays S3 `hl-mainnet-node-data/node_fills_by_block`",
        f"- expected_hourly_objects: {total}",
        f"- s3_available_objects: {s3_available}",
        f"- local_cached_objects: {cached}",
        f"- downloaded_this_run: {downloaded}",
        f"- missing_objects: {missing}",
        f"- expected_s3_size_gb: {manifest['s3_size_bytes'].sum() / 1_000_000_000:.3f}",
        f"- local_cached_size_gb: {manifest.loc[manifest['local_exists'], 'local_size_bytes'].sum() / 1_000_000_000:.3f}",
        "",
        "## Status Counts",
        "",
    ]
    for status, count in manifest["status"].value_counts().sort_index().items():
        lines.append(f"- {status}: {int(count)}")
    missing_frame = manifest[~manifest["s3_exists"]]
    if not missing_frame.empty:
        lines.extend(["", "## Missing Objects", ""])
        by_date = missing_frame.groupby("date")["hour"].apply(lambda values: ",".join(str(int(v)) for v in sorted(values))).to_dict()
        for date, hours in by_date.items():
            lines.append(f"- {date}: hours {hours}")
    lines.extend(
        [
            "",
            "## Research Use",
            "",
            "- These files contain all coins for each hour; target-coin filtering happens locally during calibration.",
            "- Use this cache for official-source fill-intensity calibration instead of Baselight.",
            "- This does not solve queue-position modeling; it only provides the official fill events needed for a better fill model.",
            "",
        ]
    )
    ensure_parent(out).write_text("\n".join(lines), encoding="utf-8")


@app.command("manifest")
def manifest(
    start_date: str = typer.Option("20250727"),
    end_date: str = typer.Option("20251231"),
    hours: str = typer.Option("0-23"),
    raw_dir: Path = typer.Option(Path("data/raw/hyperliquid-s3-node-fills")),
    out: Path = typer.Option(Path("data/clean/hyperliquid_official_fills_manifest.parquet")),
    report: Path = typer.Option(Path("docs/official-fills-cache.md")),
    workers: int = typer.Option(64, min=1),
) -> None:
    items = build_objects(start_date, end_date, hours, raw_dir)
    rows: list[dict[str, object]] = []
    typer.echo(f"[start] head official fills objects={len(items)} workers={workers}")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_head_object, item, workers * 2) for item in items]
        for index, future in enumerate(as_completed(futures), start=1):
            rows.append(future.result())
            if index % 250 == 0 or index == len(items):
                typer.echo(f"[progress] headed={index}/{len(items)}")
    frame = pd.DataFrame.from_records(rows).sort_values(["date", "hour"]).reset_index(drop=True)
    write_parquet(frame, out)
    write_cache_report(frame, report)
    typer.echo(f"[done] wrote manifest rows={len(frame)} to {out}")
    typer.echo(f"[done] wrote report to {report}")


@app.command("download")
def download(
    start_date: str = typer.Option("20250727"),
    end_date: str = typer.Option("20251231"),
    hours: str = typer.Option("0-23"),
    raw_dir: Path = typer.Option(Path("data/raw/hyperliquid-s3-node-fills")),
    out: Path = typer.Option(Path("data/clean/hyperliquid_official_fills_manifest.parquet")),
    report: Path = typer.Option(Path("docs/official-fills-cache.md")),
    workers: int = typer.Option(64, min=1),
    overwrite: bool = typer.Option(False),
) -> None:
    items = build_objects(start_date, end_date, hours, raw_dir)
    typer.echo(f"[start] head official fills objects={len(items)} workers={workers}")
    head_rows: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_head_object, item, workers * 2) for item in items]
        for index, future in enumerate(as_completed(futures), start=1):
            head_rows.append(future.result())
            if index % 250 == 0 or index == len(items):
                typer.echo(f"[progress] headed={index}/{len(items)}")

    head_by_key = {(row["date"], row["hour"]): row for row in head_rows}
    downloadable = [
        item
        for item in items
        if head_by_key[(item.date, item.hour)]["s3_exists"]
        and (overwrite or not head_by_key[(item.date, item.hour)]["size_matches"])
    ]
    typer.echo(f"[start] download official fills objects={len(downloadable)} workers={workers}")
    download_updates: dict[tuple[str, int], dict[str, object]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                _download_object,
                item,
                int(head_by_key[(item.date, item.hour)]["s3_size_bytes"]),
                overwrite,
                workers * 2,
            )
            for item in downloadable
        ]
        for index, future in enumerate(as_completed(futures), start=1):
            update = future.result()
            download_updates[(str(update["date"]), int(update["hour"]))] = update
            if index % 50 == 0 or index == len(downloadable):
                typer.echo(f"[progress] downloaded={index}/{len(downloadable)}")

    rows: list[dict[str, object]] = []
    for row in head_rows:
        key = (str(row["date"]), int(row["hour"]))
        if key in download_updates:
            row.update(download_updates[key])
        else:
            local_path = Path(str(row["local_path"]))
            row.update(
                {
                    "local_exists": local_path.exists(),
                    "local_size_bytes": local_path.stat().st_size if local_path.exists() else 0,
                    "size_matches": local_path.exists() and local_path.stat().st_size == int(row["s3_size_bytes"]),
                    "downloaded": False,
                    "status": row["status"] if not row["s3_exists"] else ("cached" if local_path.exists() and local_path.stat().st_size == int(row["s3_size_bytes"]) else row["status"]),
                }
            )
        rows.append(row)

    frame = pd.DataFrame.from_records(rows).sort_values(["date", "hour"]).reset_index(drop=True)
    write_parquet(frame, out)
    write_cache_report(frame, report)
    typer.echo(f"[done] wrote manifest rows={len(frame)} to {out}")
    typer.echo(f"[done] wrote report to {report}")


if __name__ == "__main__":
    app()
