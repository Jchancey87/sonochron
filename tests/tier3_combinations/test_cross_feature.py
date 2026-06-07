import sys
import subprocess
import time

def test_interaction_capture_to_timeline(client):
    """Tier 3 Test 1 (F1+F2): Ingest multiple entries and verify immediate update in chronological timeline."""
    # Capture Entry 1
    resp1 = client.post(
        "/api/entries",
        files={"file": ("morning.wav", b"data")},
        data={"local_capture_time": "2026-06-06T08:00:00Z", "notes": "Morning coffee"}
    )
    assert resp1.status_code == 200
    
    # Capture Entry 2
    resp2 = client.post(
        "/api/entries",
        files={"file": ("night.wav", b"data")},
        data={"local_capture_time": "2026-06-06T22:00:00Z", "notes": "Night sleep"}
    )
    assert resp2.status_code == 200

    # Retrieve Timeline and check chronological grouping
    timeline_resp = client.get("/api/timeline")
    assert timeline_resp.status_code == 200
    
    timeline = timeline_resp.json()
    assert len(timeline) == 1
    month_data = timeline[0]["months"][0]
    assert len(month_data["entries"]) == 2
    
    # Check that night is first (descending order)
    assert month_data["entries"][0]["id"] == resp2.json()["id"]
    assert month_data["entries"][1]["id"] == resp1.json()["id"]

def test_interaction_timeline_to_similarity_search(client):
    """Tier 3 Test 2 (F1+F4): Locate entry in timeline and use its ID for similarity search."""
    # Ingest mood-matched entries
    resp1 = client.post(
        "/api/entries",
        files={"file": ("happy1.wav", b"data")},
        data={"local_capture_time": "2026-06-06T09:00:00Z", "mood": "happy"}
    )
    resp2 = client.post(
        "/api/entries",
        files={"file": ("happy2.wav", b"data")},
        data={"local_capture_time": "2026-06-06T10:00:00Z", "mood": "happy"}
    )
    
    # Wait for indexing
    time.sleep(0.05)
    
    # Get timeline
    timeline = client.get("/api/timeline").json()
    entries = timeline[0]["months"][0]["entries"]
    
    # Find entry 1 ID from timeline
    target_entry = next(e for e in entries if e["id"] == resp1.json()["id"])
    assert target_entry is not None
    
    # Use timeline entry ID to search for similar recordings
    search_resp = client.get(f"/api/search?similarity_entry_id={target_entry['id']}")
    assert search_resp.status_code == 200
    results = search_resp.json()
    
    # Verify similar entry is found
    found_ids = [r["id"] for r in results]
    assert resp2.json()["id"] in found_ids

def test_interaction_concurrent_capture_pipeline(client):
    """Tier 3 Test 3 (F2+F3): Perform concurrent uploads and verify processing pipelines run isolated."""
    # Ingest 10 entries with distinct notes, some set to fail, some to succeed
    created_ids = []
    for i in range(10):
        notes = "fail" if i % 3 == 0 else f"normal_{i}"
        resp = client.post(
            "/api/entries",
            files={"file": (f"concur_{i}.wav", b"data")},
            data={"local_capture_time": "2026-06-06T12:00:00Z", "notes": notes}
        )
        created_ids.append((resp.json()["id"], notes))
        
    # Wait for all background tasks to execute
    time.sleep(0.1)
    
    # Verify stages are correct for all entries
    for entry_id, notes in created_ids:
        entry = client.get(f"/api/entries/{entry_id}").json()
        if "fail" in notes:
            assert entry["stage"] == "failed"
        else:
            assert entry["stage"] == "ready"

def test_interaction_pipeline_to_search_rebuild(client):
    """Tier 3 Test 4 (F3+F4): Trigger pipeline failures, run index rebuild, and check search sanity."""
    # Ingest one failure and one success
    f_resp = client.post(
        "/api/entries",
        files={"file": ("bad.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:00:00Z", "notes": "fail"}
    )
    s_resp = client.post(
        "/api/entries",
        files={"file": ("good.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:30:00Z", "notes": "superb day"}
    )
    
    # Wait for pipeline
    time.sleep(0.1)
    
    # Run CLI Rebuild
    res = subprocess.run([sys.executable, "-m", "tests.mock_cli", "reindex"], capture_output=True)
    assert res.returncode == 0
    
    # Search for 'day' (matches success)
    s_results = client.get("/api/search?q=day").json()
    found_ids = [r["id"] for r in s_results]
    assert s_resp.json()["id"] in found_ids
    assert f_resp.json()["id"] not in found_ids
    
    # Search for 'fail' (should not find the failed entry since it's not indexed)
    f_results = client.get("/api/search?q=fail").json()
    assert f_resp.json()["id"] not in [r["id"] for r in f_results]
