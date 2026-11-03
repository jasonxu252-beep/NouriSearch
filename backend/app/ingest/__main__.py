"""Command line for loading data.

python -m app.ingest vocabulary
python -m app.ingest download --data-dir ../data/raw
python -m app.ingest fdc --data-dir ../data/raw
python -m app.ingest all --data-dir ../data/raw
python -m app.ingest benchmark
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_engine
from app.ingest.fdc_loader import download_all, ingest_fdc
from app.ingest.fdc_rules import FdcMappings
from app.ingest.vocabulary import load_vocabulary
from app.logging_config import configure_logging
from app.services.rebuild_benchmark import run_rebuild_benchmark


def run_vocabulary() -> None:
    with Session(get_engine()) as session, session.begin():
        load_vocabulary(session)


def run_benchmark() -> None:
    with Session(get_engine()) as session:
        results = run_rebuild_benchmark(session)
    sys.stdout.write(json.dumps([asdict(r) for r in results], indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    parser = argparse.ArgumentParser(prog="python -m app.ingest")
    parser.add_argument("target", choices=["vocabulary", "download", "fdc", "all", "benchmark"])
    parser.add_argument("--data-dir", type=Path, default=Path("../data/raw"))
    args = parser.parse_args(argv)

    if args.target == "download":
        download_all(args.data_dir, FdcMappings.load())
    if args.target in ("vocabulary", "all"):
        run_vocabulary()
    if args.target in ("fdc", "all"):
        ingest_fdc(get_engine(), args.data_dir)
    if args.target == "benchmark":
        run_benchmark()
    return 0


if __name__ == "__main__":
    sys.exit(main())
