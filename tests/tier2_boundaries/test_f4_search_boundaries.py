import sys
import subprocess
import time

def test_search_special_characters(client):
    """F4 Boundary Test 1: Search queries containing special characters are processed safely."""
    resp = client.post(
        "/api/entries",
        files={"file": ("test.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:00:00Z", "notes": "Find me at home!"}
    )
    entry_id = resp.json()["id"]
    
    # Wait for indexing
    time.sleep(0.05)
    
    # Query contains special characters
    search_resp = client.get("/api/search?q=home!!!")
    assert search_resp.status_code == 200
    results = search_resp.json()
    assert len(results) > 0
    assert results[0]["id"] == entry_id

def test_search_case_insensitivity(client):
    """F4 Boundary Test 2: Search queries are case-insensitive."""
    resp = client.post(
        "/api/entries",
        files={"file": ("test.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:00:00Z", "notes": "PlAtYpUs"}
    )
    entry_id = resp.json()["id"]
    time.sleep(0.05)
    
    # Query in lowercase
    resp1 = client.get("/api/search?q=platypus")
    assert len(resp1.json()) > 0
    assert resp1.json()[0]["id"] == entry_id

    # Query in uppercase
    resp2 = client.get("/api/search?q=PLATYPUS")
    assert len(resp2.json()) > 0
    assert resp2.json()[0]["id"] == entry_id

def test_search_nonexistent_similarity_id(client):
    """F4 Boundary Test 3: Search with nonexistent similarity_entry_id is handled gracefully."""
    search_resp = client.get("/api/search?similarity_entry_id=00000000-0000-0000-0000-000000000000")
    assert search_resp.status_code == 200
    assert search_resp.json() == []

def test_cli_rebuild_no_arguments(client):
    """F4 Boundary Test 4: Running mock CLI with no command returns non-zero code."""
    res = subprocess.run(
        [sys.executable, "-m", "tests.mock_cli"],
        capture_output=True,
        text=True
    )
    assert res.returncode == 1
    assert "Usage:" in res.stdout or "Usage:" in res.stderr

def test_cli_rebuild_unknown_command(client):
    """F4 Boundary Test 5: Running mock CLI with unknown command returns non-zero code."""
    res = subprocess.run(
        [sys.executable, "-m", "tests.mock_cli", "invalid-cmd"],
        capture_output=True,
        text=True
    )
    assert res.returncode == 1
    assert "Unknown command" in res.stdout or "Unknown command" in res.stderr
