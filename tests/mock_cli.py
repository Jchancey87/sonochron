import sys
import os
import json

DB_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "mock_db.json"))

def load_db():
    if not os.path.exists(DB_FILE):
        return {"entries": {}, "idempotency_keys": {}}
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"entries": {}, "idempotency_keys": {}}

def save_db(db):
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

def rebuild_index():
    print("Purging current Qdrant vector index...")
    db = load_db()
    
    entries = db.get("entries", {})
    if not entries:
        print("No entries found in database. Index is empty.")
        save_db(db)
        return
        
    print(f"Found {len(entries)} entries to index.")
    
    indexed_count = 0
    failed_count = 0
    
    for entry_id, entry in entries.items():
        notes = (entry.get("context", {}).get("notes") or "").lower()
        if "fail" in notes:
            entry["stage"] = "failed"
            failed_count += 1
            print(f"Skipping failed entry {entry_id} (marked as fail)")
        else:
            entry["stage"] = "ready"
            indexed_count += 1
            print(f"Indexing entry {entry_id} - status: ready")
            
    save_db(db)
    print(f"Index rebuild completed: {indexed_count} indexed, {failed_count} failed.")

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m tests.mock_cli <command>")
        print("Available commands: reindex, rebuild-index")
        sys.exit(1)
        
    command = sys.argv[1]
    if command in ("rebuild-index", "reindex"):
        rebuild_index()
        sys.exit(0)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

if __name__ == "__main__":
    main()
