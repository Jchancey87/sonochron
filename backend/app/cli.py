"""
cli.py — Sonochron command-line tooling.

Usage:
  python -m app.cli reindex
  python -m app.cli reindex --storage-path /custom/qdrant/path
  python -m app.cli check-entry <entry-id>
"""

import sys
import uuid
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("sonochron.cli")


def cmd_reindex(args):
    """Purge and rebuild the entire Qdrant index from Postgres."""
    from app.search import reindex_all
    print(f"Starting full reindex from Postgres → Qdrant ({args.storage_path})...")
    count = reindex_all(storage_path=args.storage_path)
    print(f"✅ Reindex complete: {count} entries indexed.")


def cmd_analyze_assets(args):
    """Manually trigger key/bpm analysis for any assets lacking it."""
    import asyncio
    from app.main import analyze_existing_assets
    print("Triggering manual analysis of existing assets...")
    asyncio.run(analyze_existing_assets())
    print("✅ Analysis complete.")


def cmd_check_entry(args):
    """Inspect a single diary entry's pipeline stage state."""
    from sqlmodel import Session
    from app.database import engine, DiaryEntry, EntryContext, SampleAsset

    try:
        entry_id = uuid.UUID(args.entry_id)
    except ValueError:
        print(f"❌ Invalid UUID: {args.entry_id}")
        sys.exit(1)

    with Session(engine) as session:
        entry = session.get(DiaryEntry, entry_id)
        if not entry:
            print(f"❌ Entry {entry_id} not found in Postgres.")
            sys.exit(1)

        context = session.exec(
            __import__("sqlmodel").select(EntryContext).where(EntryContext.entry_id == entry_id)
        ).first()
        asset = session.exec(
            __import__("sqlmodel").select(SampleAsset).where(SampleAsset.entry_id == entry_id)
        ).first()

    print(f"\n{'─'*50}")
    print(f"  Entry ID : {entry.id}")
    print(f"  Title    : {entry.title or '(none)'}")
    print(f"  Captured : {entry.local_capture_time}")
    print(f"  Stage    : {entry.stage}")
    print(f"  Created  : {entry.created_at}")
    print(f"  Updated  : {entry.updated_at}")
    if context:
        print(f"\n  Context:")
        print(f"    Mood       : {context.mood or '-'}")
        print(f"    Location   : {context.location or '-'}")
        print(f"    Companions : {', '.join(context.companions) if context.companions else '-'}")
        print(f"    Notes      : {context.notes or '-'}")
    if asset:
        print(f"\n  Asset:")
        print(f"    File       : {asset.filename}")
        print(f"    Path       : {asset.filepath}")
        print(f"    SHA256     : {asset.checksum_sha256 or '-'}")
        print(f"    Size       : {asset.byte_size or '-'} bytes")
    print(f"{'─'*50}\n")


def main():
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Sonochron CLI — admin and repair tooling",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # reindex subcommand
    p_reindex = subparsers.add_parser(
        "reindex",
        aliases=["rebuild-index"],
        help="Purge and rebuild the Qdrant vector index from Postgres state",
    )
    p_reindex.add_argument(
        "--storage-path",
        default="backend/qdrant_storage",
        help="Path to local Qdrant storage directory (default: backend/qdrant_storage)",
    )
    p_reindex.set_defaults(func=cmd_reindex)

    # check-entry subcommand
    p_check = subparsers.add_parser(
        "check-entry",
        help="Inspect a single diary entry's current stage state",
    )
    p_check.add_argument("entry_id", help="Diary entry UUID")
    p_check.set_defaults(func=cmd_check_entry)

    # analyze-assets subcommand
    p_analyze = subparsers.add_parser(
        "analyze-assets",
        help="Run audio key and BPM analysis on existing sound assets",
    )
    p_analyze.set_defaults(func=cmd_analyze_assets)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
