import sys
import subprocess
import time

def test_search_text_match(client):
    """F4 Test 1: Ingest entry and search using specific keyword in notes."""
    resp = client.post(
        "/api/entries",
        files={"file": ("test.wav", b"data")},
        data={
            "local_capture_time": "2026-06-06T12:00:00Z",
            "notes": "Spotted a wild platypus in the creek."
        }
    )
    entry_id = resp.json()["id"]
    
    # Wait for indexing
    for _ in range(20):
        if client.get(f"/api/entries/{entry_id}").json()["stage"] == "ready":
            break
        time.sleep(0.01)

    search_resp = client.get("/api/search?q=platypus")
    assert search_resp.status_code == 200
    results = search_resp.json()
    assert len(results) > 0
    assert results[0]["id"] == entry_id
    assert results[0]["score"] > 0.0

def test_search_audio_similarity(client):
    """F4 Test 2: Ingest entries and search using audio similarity (sharing same mood)."""
    # Entry 1
    resp1 = client.post(
        "/api/entries",
        files={"file": ("1.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:00:00Z", "mood": "excited"}
    )
    id1 = resp1.json()["id"]
    
    # Entry 2
    resp2 = client.post(
        "/api/entries",
        files={"file": ("2.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:30:00Z", "mood": "excited"}
    )
    id2 = resp2.json()["id"]
    
    # Wait for indexing
    time.sleep(0.05)

    search_resp = client.get(f"/api/search?similarity_entry_id={id1}")
    assert search_resp.status_code == 200
    results = search_resp.json()
    assert len(results) >= 2
    # The first result is the entry itself (score 1.0)
    assert results[0]["id"] == id1
    assert results[0]["score"] == 1.0
    # The second result is the other excited entry
    assert results[1]["id"] == id2
    assert results[1]["score"] > 0.0

def test_search_no_results(client):
    """F4 Test 3: Search with query matching nothing returns empty results."""
    client.post(
        "/api/entries",
        files={"file": ("test.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:00:00Z", "notes": "ordinary day"}
    )
    
    search_resp = client.get("/api/search?q=xyzzy")
    assert search_resp.status_code == 200
    assert search_resp.json() == []

def test_cli_rebuild_index(client):
    """F4 Test 4: Verify reindex CLI updates entry stage to ready."""
    resp = client.post(
        "/api/entries",
        files={"file": ("test.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:00:00Z"}
    )
    entry_id = resp.json()["id"]
    
    # Manually reset stage back to uploaded to simulate unindexed state
    from tests.mock_backend import update_entry_stage
    update_entry_stage(entry_id, "uploaded")
    
    assert client.get(f"/api/entries/{entry_id}").json()["stage"] == "uploaded"

    # Run mock CLI reindex command as subprocess
    res = subprocess.run(
        [sys.executable, "-m", "tests.mock_cli", "reindex"],
        capture_output=True,
        text=True
    )
    assert res.returncode == 0
    assert "Index rebuild completed" in res.stdout

    # Verify that it is now ready
    assert client.get(f"/api/entries/{entry_id}").json()["stage"] == "ready"

def test_cli_rebuild_leaves_failed(client):
    """F4 Test 5: Reindex CLI command does not re-index failed entries."""
    # Failed entry
    resp1 = client.post(
        "/api/entries",
        files={"file": ("test1.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:00:00Z", "notes": "fail"}
    )
    id1 = resp1.json()["id"]
    
    # Successful entry
    resp2 = client.post(
        "/api/entries",
        files={"file": ("test2.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:30:00Z", "notes": "normal"}
    )
    id2 = resp2.json()["id"]

    # Wait for pipeline completion
    time.sleep(0.1)
    
    assert client.get(f"/api/entries/{id1}").json()["stage"] == "failed"
    assert client.get(f"/api/entries/{id2}").json()["stage"] == "ready"

    # Run mock CLI reindex command
    res = subprocess.run(
        [sys.executable, "-m", "tests.mock_cli", "reindex"],
        capture_output=True,
        text=True
    )
    assert res.returncode == 0

    # Verify id1 is still failed and id2 is still ready
    assert client.get(f"/api/entries/{id1}").json()["stage"] == "failed"
    assert client.get(f"/api/entries/{id2}").json()["stage"] == "ready"
