#!/usr/bin/env python3
"""Download and featurize Hyperliquid historical S3 L2 book snapshots.

The script intentionally uses the AWS CLI and lz4 CLI because Hyperliquid's
public archive bucket is requester-pays and the official examples use those
tools directly.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None
    Config = None
    ClientError = Exception

try:
    import lz4.frame as lz4_frame
except ImportError:
    lz4_frame = None


BUCKET = "hyperliquid-archive"
DEFAULT_DATATYPE = "l2Book"
DEFAULT_DEPTH_LEVELS = (1, 5, 10)
_S3_CLIENT = None


def default_aws_bin() -> str:
    local_aws = Path.home() / ".local" / "bin" / "aws"
    if local_aws.exists():
        return str(local_aws)
    return "aws"


@dataclass(frozen=True)
class MarketDataFile:
    coin: str
    date: str
    hour: int
    datatype: str
    raw_dir: Path

    @property
    def s3_key(self) -> str:
        return (
            "market_data/"
            f"{self.date}/{self.hour}/{self.datatype}/{self.coin}.lz4"
        )

    @property
    def s3_uri(self) -> str:
        return f"s3://{BUCKET}/{self.s3_key}"

    @property
    def compressed_path(self) -> Path:
        return (
            self.raw_dir
            / self.datatype
            / self.coin
            / self.date
            / str(self.hour)
            / f"{self.coin}.lz4"
        )

    @property
    def decompressed_path(self) -> Path:
        return self.compressed_path.with_suffix("")


@dataclass
class WorkResult:
    attempted: int = 1
    downloaded_or_found: int = 0
    source_ready: int = 0
    feature_files: int = 0
    feature_rows: int = 0
    status: str = "ok"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download Hyperliquid S3 market_data files and convert l2Book JSONL "
            "snapshots to CSV features."
        )
    )
    parser.add_argument(
        "--coins",
        nargs="+",
        required=True,
        help="Coin symbols, for example: BTC ETH SOL",
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="Start date as YYYYMMDD or YYYY-MM-DD.",
    )
    parser.add_argument(
        "--end-date",
        help="End date as YYYYMMDD or YYYY-MM-DD. Defaults to --start-date.",
    )
    parser.add_argument(
        "--hours",
        default="0-23",
        help="Hours to fetch, for example '9', '0,1,2', or '0-23'. Default: 0-23.",
    )
    parser.add_argument(
        "--datatype",
        default=DEFAULT_DATATYPE,
        help=f"Hyperliquid market_data datatype. Default: {DEFAULT_DATATYPE}.",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw/hyperliquid"),
        help="Where compressed raw .lz4 files are stored.",
    )
    parser.add_argument(
        "--features-dir",
        type=Path,
        default=Path("data/processed/hyperliquid"),
        help="Where feature files are written.",
    )
    parser.add_argument(
        "--features-format",
        choices=("csv", "csv.gz"),
        default="csv.gz",
        help="Feature output format. Default: csv.gz.",
    )
    parser.add_argument(
        "--depth-levels",
        default="1,5,10",
        help="Comma-separated L2 depths for aggregate features. Default: 1,5,10.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Use already downloaded .lz4 files.",
    )
    parser.add_argument(
        "--skip-decompress",
        action="store_true",
        help="Use already decompressed JSONL files. Requires --keep-decompressed.",
    )
    parser.add_argument(
        "--keep-decompressed",
        action="store_true",
        help=(
            "Write and keep decompressed JSONL files. By default the pipeline "
            "streams directly from .lz4 to features to save disk."
        ),
    )
    parser.add_argument(
        "--skip-features",
        action="store_true",
        help="Only download files. Also decompresses if --keep-decompressed is set.",
    )
    parser.add_argument(
        "--delete-compressed",
        action="store_true",
        help="Delete each .lz4 raw file after features are written.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing local files.",
    )
    parser.add_argument(
        "--aws-bin",
        default=default_aws_bin(),
        help="AWS CLI binary to use. Defaults to ~/.local/bin/aws when present.",
    )
    parser.add_argument(
        "--download-backend",
        choices=("boto3", "awscli"),
        default="boto3" if boto3 is not None else "awscli",
        help="S3 download backend. Default: boto3 when installed, otherwise awscli.",
    )
    parser.add_argument(
        "--lz4-bin",
        default="lz4",
        help="lz4 binary to use. Default: lz4.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of files to process concurrently. Default: 1.",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=100,
        help="Print one aggregate progress line every N completed files.",
    )
    return parser.parse_args()


def normalize_date(value: str) -> str:
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y%m%d")
        except ValueError:
            pass
    raise ValueError(f"Invalid date {value!r}; expected YYYYMMDD or YYYY-MM-DD")


def iter_dates(start_date: str, end_date: str) -> Iterable[str]:
    start = datetime.strptime(normalize_date(start_date), "%Y%m%d")
    end = datetime.strptime(normalize_date(end_date), "%Y%m%d")
    if end < start:
        raise ValueError("--end-date must be on or after --start-date")

    current = start
    while current <= end:
        yield current.strftime("%Y%m%d")
        current += timedelta(days=1)


def parse_hours(value: str) -> list[int]:
    hours: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            raw_start, raw_end = part.split("-", 1)
            start, end = int(raw_start), int(raw_end)
            hours.update(range(start, end + 1))
        else:
            hours.add(int(part))

    invalid = [hour for hour in hours if hour < 0 or hour > 23]
    if invalid:
        raise ValueError(f"Invalid hour(s): {invalid}; expected 0..23")
    return sorted(hours)


def parse_depth_levels(value: str) -> list[int]:
    levels = sorted({int(item.strip()) for item in value.split(",") if item.strip()})
    if not levels or any(level < 1 for level in levels):
        raise ValueError("--depth-levels must contain positive integers")
    return levels


def require_binary(binary: str) -> None:
    if shutil.which(binary) is None:
        raise SystemExit(
            f"Missing required command {binary!r}. Install it or pass the correct "
            f"path with --aws-bin/--lz4-bin."
        )


def require_lz4(lz4_bin: str) -> None:
    if shutil.which(lz4_bin) is None and lz4_frame is None:
        raise SystemExit(
            f"Missing required command {lz4_bin!r} and Python package 'lz4'. "
            "Install one of them or pass the correct path with --lz4-bin."
        )


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def temp_download_path(item: MarketDataFile) -> Path:
    return item.compressed_path.with_name(
        f"{item.compressed_path.name}.part.{time.time_ns()}"
    )


def s3_client():
    global _S3_CLIENT
    if boto3 is None or Config is None:
        raise RuntimeError("boto3 is not installed")
    if _S3_CLIENT is None:
        _S3_CLIENT = boto3.client(
            "s3",
            config=Config(
                retries={"max_attempts": 8, "mode": "adaptive"},
                max_pool_connections=1024,
            ),
        )
    return _S3_CLIENT


def download_file_boto3(item: MarketDataFile, force: bool) -> bool:
    if item.compressed_path.exists() and not force:
        print(f"[skip] exists {item.compressed_path}")
        return True

    item.compressed_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = temp_download_path(item)
    print(f"[download] {item.s3_uri}")
    try:
        s3_client().download_file(
            BUCKET,
            item.s3_key,
            str(temp_path),
            ExtraArgs={"RequestPayer": "requester"},
        )
    except ClientError as exc:
        temp_path.unlink(missing_ok=True)
        print(
            f"[warn] download failed for {item.coin} {item.date} hour {item.hour}: "
            f"{exc}",
            file=sys.stderr,
        )
        return False
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        print(
            f"[warn] download failed for {item.coin} {item.date} hour {item.hour}: "
            f"{exc}",
            file=sys.stderr,
        )
        return False
    temp_path.replace(item.compressed_path)
    return True


def download_file_awscli(item: MarketDataFile, aws_bin: str, force: bool) -> bool:
    if item.compressed_path.exists() and not force:
        print(f"[skip] exists {item.compressed_path}")
        return True

    item.compressed_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = temp_download_path(item)
    print(f"[download] {item.s3_uri}")
    result = run(
        [
            aws_bin,
            "s3",
            "cp",
            item.s3_uri,
            str(temp_path),
            "--request-payer",
            "requester",
            "--no-progress",
        ]
    )
    if result.returncode != 0:
        temp_path.unlink(missing_ok=True)
        print(
            f"[warn] download failed for {item.coin} {item.date} hour {item.hour}: "
            f"{result.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    temp_path.replace(item.compressed_path)
    return True


def download_file(item: MarketDataFile, args: argparse.Namespace) -> bool:
    if args.download_backend == "boto3":
        return download_file_boto3(item, args.force)
    return download_file_awscli(item, args.aws_bin, args.force)


def decompress_file(item: MarketDataFile, lz4_bin: str, force: bool) -> bool:
    if not item.compressed_path.exists():
        print(f"[warn] missing compressed file {item.compressed_path}", file=sys.stderr)
        return False
    if item.decompressed_path.exists() and not force:
        print(f"[skip] exists {item.decompressed_path}")
        return True

    if shutil.which(lz4_bin) is None:
        if lz4_frame is None:
            print(
                f"[warn] no lz4 backend available for {item.compressed_path}",
                file=sys.stderr,
            )
            return False
        print(f"[decompress] {item.compressed_path}")
        try:
            with lz4_frame.open(item.compressed_path, "rb") as source:
                with item.decompressed_path.open("wb") as target:
                    shutil.copyfileobj(source, target)
        except Exception as exc:
            item.decompressed_path.unlink(missing_ok=True)
            print(
                f"[warn] decompress failed for {item.compressed_path}: {exc}",
                file=sys.stderr,
            )
            return False
        return True

    print(f"[decompress] {item.compressed_path}")
    result = run(
        [
            lz4_bin,
            "-d",
            "-f",
            str(item.compressed_path),
            str(item.decompressed_path),
        ]
    )
    if result.returncode != 0:
        print(
            f"[warn] decompress failed for {item.compressed_path}: "
            f"{result.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def as_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def sum_size(levels: list[dict[str, object]], depth: int) -> float:
    return sum(float(level["sz"]) for level in levels[:depth])


def sum_notional(levels: list[dict[str, object]], depth: int) -> float:
    return sum(float(level["px"]) * float(level["sz"]) for level in levels[:depth])


def imbalance(bid_depth: float, ask_depth: float) -> float | None:
    total = bid_depth + ask_depth
    if total == 0:
        return None
    return (bid_depth - ask_depth) / total


def feature_columns(depth_levels: list[int]) -> list[str]:
    columns = [
        "exchange_time_ms",
        "archive_time",
        "coin",
        "best_bid_px",
        "best_bid_sz",
        "best_bid_n",
        "best_ask_px",
        "best_ask_sz",
        "best_ask_n",
        "mid",
        "spread",
        "spread_bps",
        "bid_levels",
        "ask_levels",
    ]
    for depth in depth_levels:
        columns.extend(
            [
                f"bid_depth_{depth}",
                f"ask_depth_{depth}",
                f"imbalance_{depth}",
                f"bid_notional_{depth}",
                f"ask_notional_{depth}",
            ]
        )
    return columns


def extract_l2book_features(
    input_path: Path,
    output_path: Path,
    depth_levels: list[int],
) -> int:
    with input_path.open("r", encoding="utf-8") as source:
        return extract_l2book_features_from_lines(
            source,
            str(input_path),
            output_path,
            depth_levels,
        )


def open_feature_output(output_path: Path):
    if output_path.name.endswith(".gz"):
        return gzip.open(output_path, "wt", newline="", encoding="utf-8")
    return output_path.open("w", newline="", encoding="utf-8")


def extract_l2book_features_from_lines(
    lines: Iterable[str],
    source_label: str,
    output_path: Path,
    depth_levels: list[int],
) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = feature_columns(depth_levels)
    rows_written = 0

    with open_feature_output(output_path) as target:
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()

        for line_number, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                raw = event["raw"]
                data = raw["data"]
                bids, asks = data["levels"]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                print(
                    f"[warn] bad line {line_number} in {source_label}: {exc}",
                    file=sys.stderr,
                )
                continue

            if not bids or not asks:
                continue

            best_bid = bids[0]
            best_ask = asks[0]
            best_bid_px = as_float(best_bid.get("px"))
            best_ask_px = as_float(best_ask.get("px"))
            best_bid_sz = as_float(best_bid.get("sz"))
            best_ask_sz = as_float(best_ask.get("sz"))

            if best_bid_px is None or best_ask_px is None:
                continue

            mid = (best_bid_px + best_ask_px) / 2
            spread = best_ask_px - best_bid_px
            row: dict[str, object] = {
                "exchange_time_ms": data.get("time"),
                "archive_time": event.get("time"),
                "coin": data.get("coin"),
                "best_bid_px": best_bid_px,
                "best_bid_sz": best_bid_sz,
                "best_bid_n": best_bid.get("n"),
                "best_ask_px": best_ask_px,
                "best_ask_sz": best_ask_sz,
                "best_ask_n": best_ask.get("n"),
                "mid": mid,
                "spread": spread,
                "spread_bps": (spread / mid) * 10_000 if mid else None,
                "bid_levels": len(bids),
                "ask_levels": len(asks),
            }

            for depth in depth_levels:
                bid_depth = sum_size(bids, depth)
                ask_depth = sum_size(asks, depth)
                row[f"bid_depth_{depth}"] = bid_depth
                row[f"ask_depth_{depth}"] = ask_depth
                row[f"imbalance_{depth}"] = imbalance(bid_depth, ask_depth)
                row[f"bid_notional_{depth}"] = sum_notional(bids, depth)
                row[f"ask_notional_{depth}"] = sum_notional(asks, depth)

            writer.writerow(row)
            rows_written += 1

    return rows_written


def extract_l2book_features_from_lz4(
    item: MarketDataFile,
    output_path: Path,
    depth_levels: list[int],
    lz4_bin: str,
) -> int | None:
    print(f"[features] {item.compressed_path} -> {output_path}")
    if shutil.which(lz4_bin) is None:
        if lz4_frame is None:
            print(
                f"[warn] no lz4 backend available for {item.compressed_path}",
                file=sys.stderr,
            )
            return None
        try:
            with lz4_frame.open(item.compressed_path, mode="rt", encoding="utf-8") as source:
                return extract_l2book_features_from_lines(
                    source,
                    str(item.compressed_path),
                    output_path,
                    depth_levels,
                )
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            print(
                f"[warn] lz4 stream failed for {item.compressed_path}: {exc}",
                file=sys.stderr,
            )
            return None

    process = subprocess.Popen(
        [lz4_bin, "-dc", str(item.compressed_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.stdout is None:
        raise RuntimeError("failed to open lz4 stdout")

    rows = extract_l2book_features_from_lines(
        process.stdout,
        str(item.compressed_path),
        output_path,
        depth_levels,
    )
    stderr = process.stderr.read() if process.stderr is not None else ""
    returncode = process.wait()
    if returncode != 0:
        output_path.unlink(missing_ok=True)
        print(
            f"[warn] lz4 stream failed for {item.compressed_path}: {stderr.strip()}",
            file=sys.stderr,
        )
        return None
    return rows


def features_output_path(
    item: MarketDataFile,
    features_dir: Path,
    features_format: str,
) -> Path:
    filename = f"{item.hour:02d}.csv"
    if features_format == "csv.gz":
        filename += ".gz"
    return features_dir / item.datatype / item.coin / item.date / filename


def build_work_items(
    coins: list[str],
    dates: list[str],
    hours: list[int],
    datatype: str,
    raw_dir: Path,
) -> list[MarketDataFile]:
    return [
        MarketDataFile(
            coin=coin,
            date=date,
            hour=hour,
            datatype=datatype,
            raw_dir=raw_dir,
        )
        for coin in coins
        for date in dates
        for hour in hours
    ]


def process_item(
    item: MarketDataFile,
    args: argparse.Namespace,
    depth_levels: list[int],
) -> WorkResult:
    if not args.skip_features and item.datatype != DEFAULT_DATATYPE:
        print(
            f"[warn] feature extraction only supports {DEFAULT_DATATYPE}; "
            f"skipping {item.datatype}",
            file=sys.stderr,
        )
        return WorkResult(status="unsupported_datatype")

    output_path = None
    if not args.skip_features:
        output_path = features_output_path(
            item,
            args.features_dir,
            args.features_format,
        )
        if output_path.exists() and not args.force:
            print(f"[skip] exists {output_path}")
            return WorkResult(feature_files=1, status="skipped_feature")

    if args.skip_download:
        download_ok = item.compressed_path.exists()
        if not download_ok:
            print(
                f"[warn] --skip-download but missing {item.compressed_path}",
                file=sys.stderr,
            )
    else:
        download_ok = download_file(item, args)
    if not download_ok:
        return WorkResult(status="download_failed")

    result = WorkResult(downloaded_or_found=1)

    if args.skip_features:
        if args.keep_decompressed:
            if args.skip_decompress:
                if not item.decompressed_path.exists():
                    print(
                        f"[warn] --skip-decompress but missing {item.decompressed_path}",
                        file=sys.stderr,
                    )
                    return result
            elif not decompress_file(item, args.lz4_bin, args.force):
                return result
            result.source_ready = 1
        return result

    if output_path is None:
        raise RuntimeError("missing output path")

    if args.keep_decompressed:
        if args.skip_decompress:
            if not item.decompressed_path.exists():
                print(
                    f"[warn] --skip-decompress but missing {item.decompressed_path}",
                    file=sys.stderr,
                )
                return result
        elif not decompress_file(item, args.lz4_bin, args.force):
            return result
        result.source_ready = 1
        print(f"[features] {item.decompressed_path} -> {output_path}")
        rows = extract_l2book_features(
            item.decompressed_path,
            output_path,
            depth_levels,
        )
    else:
        result.source_ready = 1
        rows = extract_l2book_features_from_lz4(
            item,
            output_path,
            depth_levels,
            args.lz4_bin,
        )
        if rows is None:
            return result

    print(f"[features] wrote {rows} rows")
    result.feature_files = 1
    result.feature_rows = rows

    if args.delete_compressed:
        item.compressed_path.unlink(missing_ok=True)
        print(f"[delete] {item.compressed_path}")

    return result


def add_result(total: WorkResult, result: WorkResult) -> None:
    total.attempted += result.attempted
    total.downloaded_or_found += result.downloaded_or_found
    total.source_ready += result.source_ready
    total.feature_files += result.feature_files
    total.feature_rows += result.feature_rows


def print_progress(completed: int, total_items: int, started_at: float) -> None:
    elapsed = max(time.monotonic() - started_at, 0.001)
    rate_per_min = completed / elapsed * 60
    remaining = max(total_items - completed, 0)
    eta_seconds = remaining / (completed / elapsed) if completed else 0
    print(
        "[progress] "
        f"completed={completed}/{total_items} "
        f"rate_files_per_min={rate_per_min:.1f} "
        f"eta_minutes={eta_seconds / 60:.1f}"
    )


def main() -> int:
    args = parse_args()
    if args.download_backend == "awscli":
        require_binary(args.aws_bin)
    elif boto3 is None:
        raise SystemExit("boto3 backend requested but boto3 is not installed")
    require_lz4(args.lz4_bin)
    if args.skip_decompress and not args.keep_decompressed:
        raise SystemExit("--skip-decompress requires --keep-decompressed")
    if args.workers < 1:
        raise SystemExit("--workers must be >= 1")

    end_date = args.end_date or args.start_date
    dates = list(iter_dates(args.start_date, end_date))
    hours = parse_hours(args.hours)
    depth_levels = parse_depth_levels(args.depth_levels)
    coins = [coin.upper() for coin in args.coins]
    work_items = build_work_items(coins, dates, hours, args.datatype, args.raw_dir)
    total_items = len(work_items)
    totals = WorkResult(attempted=0)
    started_at = time.monotonic()

    print(
        "[start] "
        f"items={total_items} "
        f"workers={args.workers} "
        f"coins={','.join(coins)} "
        f"dates={dates[0]}..{dates[-1]} "
        f"hours={hours[0]}..{hours[-1]}"
    )

    if args.workers == 1:
        for completed, item in enumerate(work_items, start=1):
            add_result(totals, process_item(item, args, depth_levels))
            if completed % args.progress_interval == 0 or completed == total_items:
                print_progress(completed, total_items, started_at)
    else:
        completed = 0
        executor_cls = ProcessPoolExecutor if args.skip_download and not args.skip_features else ThreadPoolExecutor
        with executor_cls(max_workers=args.workers) as executor:
            futures = [
                executor.submit(process_item, item, args, depth_levels)
                for item in work_items
            ]
            for future in as_completed(futures):
                completed += 1
                try:
                    result = future.result()
                except Exception as exc:
                    result = WorkResult(status="exception")
                    print(f"[warn] worker exception: {exc}", file=sys.stderr)
                add_result(totals, result)
                if completed % args.progress_interval == 0 or completed == total_items:
                    print_progress(completed, total_items, started_at)

    print(
        "[done] "
        f"attempted={totals.attempted} "
        f"downloaded_or_found={totals.downloaded_or_found} "
        f"source_ready={totals.source_ready} "
        f"feature_files={totals.feature_files} "
        f"feature_rows={totals.feature_rows}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
