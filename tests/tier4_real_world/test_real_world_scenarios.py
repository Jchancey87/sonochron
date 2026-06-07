import sys
import os
import subprocess
import time

def test_scenario_day_of_recording(client):
    """Tier 4 Scenario 1: A Day of Recording.
    Ingest multiple entries throughout a single day.
    Verify correct ordering and metadata storage.
    """
    times = [
        ("2026-06-06T08:15:00Z", "morning", "Making breakfast in the kitchen"),
        ("2026-06-06T13:45:00Z", "focused", "Deep work session at the office desk"),
        ("2026-06-06T20:30:00Z", "relaxed", "Reading a novel in the living room")
    ]
    
    entry_ids = []
    for cap_time, mood, notes in times:
        resp = client.post(
            "/api/entries",
            files={"file": (f"{mood}.wav", f"audio_{mood}".encode())},
            data={
                "local_capture_time": cap_time,
                "mood": mood,
                "location": "home" if mood != "focused" else "office",
                "notes": notes
            }
        )
        assert resp.status_code == 200
        entry_ids.append(resp.json()["id"])
        
    # Check that they appear correctly on the timeline
    time.sleep(0.05)
    timeline_resp = client.get("/api/timeline")
    assert timeline_resp.status_code == 200
    timeline = timeline_resp.json()
    
    # Check hierarchy
    assert timeline[0]["year"] == 2026
    month_data = timeline[0]["months"][0]
    assert month_data["month"] == 6
    assert len(month_data["entries"]) == 3
    
    # Chronological descending check: evening (20:30) first, morning (08:15) last
    entries = month_data["entries"]
    assert entries[0]["id"] == entry_ids[2]
    assert entries[1]["id"] == entry_ids[1]
    assert entries[2]["id"] == entry_ids[0]

def test_scenario_search_and_discover_memory(client):
    """Tier 4 Scenario 2: Search & Discover Memory.
    Ingest memory, let pipeline index it, search for keywords.
    """
    resp = client.post(
        "/api/entries",
        files={"file": ("camping.wav", b"nature sounds")},
        data={
            "local_capture_time": "2026-06-06T22:00:00Z",
            "mood": "adventurous",
            "location": "national park",
            "companions": "john, sara",
            "notes": "Sitting around the campfire under a beautiful shooting star."
        }
    )
    entry_id = resp.json()["id"]
    
    # Wait for indexing
    time.sleep(0.05)
    
    # Search for campfire
    res1 = client.get("/api/search?q=campfire").json()
    assert len(res1) == 1
    assert res1[0]["id"] == entry_id
    
    # Search for sara
    res2 = client.get("/api/search?q=sara").json()
    assert len(res2) == 1
    assert res2[0]["id"] == entry_id
    
    # Search for star
    res3 = client.get("/api/search?q=star").json()
    assert len(res3) == 1
    assert res3[0]["id"] == entry_id

def test_scenario_timeline_navigation_and_playback(client):
    """Tier 4 Scenario 3: Timeline Navigation & Playback.
    Navigate timeline, retrieve details, and check simulated local file existence.
    """
    resp = client.post(
        "/api/entries",
        files={"file": ("voice_memo.mp3", b"simulated voice mp3 data")},
        data={"local_capture_time": "2026-06-06T15:00:00Z", "notes": "Voice diary entry"}
    )
    entry_id = resp.json()["id"]
    
    time.sleep(0.05)
    
    # Get entry details
    detail_resp = client.get(f"/api/entries/{entry_id}")
    assert detail_resp.status_code == 200
    details = detail_resp.json()
    
    # Verify file was actually written to storage folder and is readable
    filepath = details["asset"]["filepath"]
    assert os.path.exists(filepath)
    with open(filepath, "rb") as f:
        file_content = f.read()
    assert file_content == b"simulated voice mp3 data"

def test_scenario_recovering_from_index_corruption(client):
    """Tier 4 Scenario 4: Recovering from Index Corruption.
    Ingest, verify index, simulate corruption by reverting entry stages, rebuild index via CLI.
    """
    resp = client.post(
        "/api/entries",
        files={"file": ("entry.wav", b"data")},
        data={"local_capture_time": "2026-06-06T10:00:00Z", "notes": "important meeting"}
    )
    entry_id = resp.json()["id"]
    
    time.sleep(0.1)
    
    # Confirm ready
    assert client.get(f"/api/entries/{entry_id}").json()["stage"] == "ready"
    
    # Simulate corruption/loss of index state by resetting stage back to uploaded
    from tests.mock_backend import update_entry_stage
    update_entry_stage(entry_id, "uploaded")
    assert client.get(f"/api/entries/{entry_id}").json()["stage"] == "uploaded"
    
    # Run CLI rebuild
    res = subprocess.run([sys.executable, "-m", "tests.mock_cli", "reindex"], capture_output=True)
    assert res.returncode == 0
    
    # Verify index restored
    assert client.get(f"/api/entries/{entry_id}").json()["stage"] == "ready"

def test_scenario_high_volume_and_bulk_review(client):
    """Tier 4 Scenario 5: High-Volume Capture & Bulk Review.
    Upload 20 files, check that background workers process all, rebuild, and search.
    """
    ids = []
    for i in range(20):
        resp = client.post(
            "/api/entries",
            files={"file": (f"bulk_{i}.wav", b"bulk")},
            data={
                "local_capture_time": f"2026-06-06T10:{i:02d}:00Z",
                "notes": f"bulk entry number {i}"
            }
        )
        ids.append(resp.json()["id"])
        
    # Wait for indexing
    time.sleep(0.15)
    
    # Ensure they are all ready
    for entry_id in ids:
        assert client.get(f"/api/entries/{entry_id}").json()["stage"] == "ready"
        
    # Rebuild index
    res = subprocess.run([sys.executable, "-m", "tests.mock_cli", "reindex"], capture_output=True)
    assert res.returncode == 0
    
    # Get timeline
    timeline_resp = client.get("/api/timeline")
    timeline = timeline_resp.json()
    assert len(timeline[0]["months"][0]["entries"]) == 20
    
    # Search for specific one
    search_resp = client.get("/api/search?q=number 15")
    assert len(search_resp.json()) > 0
    assert search_resp.json()[0]["id"] == ids[15]
