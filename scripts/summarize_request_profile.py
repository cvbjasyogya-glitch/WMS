import argparse
import re
import sys
from collections import defaultdict


PROFILE_PATTERN = re.compile(
    r"REQUEST_PROFILE "
    r"method=(?P<method>\S+) "
    r"path=(?P<path>\S+) "
    r"endpoint=(?P<endpoint>\S*) "
    r"status=(?P<status>\d+) "
    r"duration_ms=(?P<duration_ms>-?\d+(?:\.\d+)?) "
    r"rss_before_mb=(?P<rss_before_mb>-?\d+(?:\.\d+)?) "
    r"rss_after_mb=(?P<rss_after_mb>-?\d+(?:\.\d+)?) "
    r"rss_delta_kb=(?P<rss_delta_kb>-?\d+)"
)


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _iter_lines(paths):
    if not paths:
        for line in sys.stdin:
            yield line
        return
    for path in paths:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                yield line


def main():
    parser = argparse.ArgumentParser(
        description="Ringkas log REQUEST_PROFILE menjadi daftar route paling berat."
    )
    parser.add_argument("paths", nargs="*", help="File log. Kalau kosong, baca dari stdin.")
    parser.add_argument("--limit", type=int, default=15, help="Jumlah route yang ditampilkan.")
    args = parser.parse_args()

    route_stats = defaultdict(
        lambda: {
            "hits": 0,
            "delta_total_kb": 0,
            "delta_max_kb": -10**12,
            "duration_total_ms": 0.0,
            "duration_max_ms": 0.0,
            "rss_after_max_mb": 0.0,
            "methods": set(),
            "endpoints": set(),
            "statuses": defaultdict(int),
        }
    )

    matched_lines = 0
    for line in _iter_lines(args.paths):
        match = PROFILE_PATTERN.search(line)
        if not match:
            continue
        matched_lines += 1
        data = match.groupdict()
        path = data["path"] or "-"
        stats = route_stats[path]
        stats["hits"] += 1
        stats["delta_total_kb"] += _safe_int(data["rss_delta_kb"])
        stats["delta_max_kb"] = max(stats["delta_max_kb"], _safe_int(data["rss_delta_kb"]))
        stats["duration_total_ms"] += _safe_float(data["duration_ms"])
        stats["duration_max_ms"] = max(stats["duration_max_ms"], _safe_float(data["duration_ms"]))
        stats["rss_after_max_mb"] = max(stats["rss_after_max_mb"], _safe_float(data["rss_after_mb"]))
        if data["method"]:
            stats["methods"].add(data["method"])
        if data["endpoint"]:
            stats["endpoints"].add(data["endpoint"])
        stats["statuses"][data["status"]] += 1

    if matched_lines == 0:
        print("Tidak ada baris REQUEST_PROFILE yang ditemukan.")
        print("Contoh pakai:")
        print('  sudo journalctl -u wms.service --since "30 min ago" --no-pager | python3 scripts/summarize_request_profile.py')
        return 1

    ranked = []
    for path, stats in route_stats.items():
        hits = stats["hits"] or 1
        ranked.append(
            {
                "path": path,
                "hits": hits,
                "avg_delta_kb": stats["delta_total_kb"] / hits,
                "max_delta_kb": stats["delta_max_kb"],
                "avg_duration_ms": stats["duration_total_ms"] / hits,
                "max_duration_ms": stats["duration_max_ms"],
                "max_rss_after_mb": stats["rss_after_max_mb"],
                "methods": ",".join(sorted(stats["methods"])) or "-",
                "endpoints": ",".join(sorted(stats["endpoints"])) or "-",
                "statuses": ",".join(
                    f"{status}:{count}"
                    for status, count in sorted(stats["statuses"].items(), key=lambda item: item[0])
                ),
            }
        )

    ranked.sort(
        key=lambda item: (
            item["max_delta_kb"],
            item["avg_delta_kb"],
            item["max_duration_ms"],
            item["hits"],
        ),
        reverse=True,
    )

    print("Top route dari REQUEST_PROFILE")
    print(
        "max_delta_kb | avg_delta_kb | avg_ms | max_ms | max_rss_mb | hits | methods | path | endpoint | statuses"
    )
    for item in ranked[: max(1, args.limit)]:
        print(
            f"{item['max_delta_kb']:>12.0f} | "
            f"{item['avg_delta_kb']:>12.1f} | "
            f"{item['avg_duration_ms']:>6.1f} | "
            f"{item['max_duration_ms']:>6.1f} | "
            f"{item['max_rss_after_mb']:>10.1f} | "
            f"{item['hits']:>4} | "
            f"{item['methods']:<7} | "
            f"{item['path']} | "
            f"{item['endpoints']} | "
            f"{item['statuses']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
