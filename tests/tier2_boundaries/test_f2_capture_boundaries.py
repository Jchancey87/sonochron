import uuid

def test_ingest_missing_file(client):
    """F2 Boundary Test 1: Uploading without file returns 422 validation error."""
    data = {"local_capture_time": "2026-06-06T12:00:00Z"}
    resp = client.post("/api/entries", data=data)
    assert resp.status_code == 422

def test_ingest_missing_local_capture_time(client):
    """F2 Boundary Test 2: Uploading without local_capture_time returns 422 validation error."""
    files = {"file": ("test.wav", b"data")}
    resp = client.post("/api/entries", files=files)
    assert resp.status_code == 422

def test_ingest_malformed_idempotency_key(client):
    """F2 Boundary Test 3: Uploading with malformed non-UUID idempotency key is accepted/handled."""
    files = {"file": ("test.wav", b"data")}
    data = {"local_capture_time": "2026-06-06T12:00:00Z"}
    resp = client.post("/api/entries", files=files, data=data, headers={"X-Idempotency-Key": "short-key"})
    assert resp.status_code == 200
    entry_id = resp.json()["id"]
    
    # Try again with same key
    resp2 = client.post("/api/entries", files=files, data=data, headers={"X-Idempotency-Key": "short-key"})
    assert resp2.status_code == 200
    assert resp2.json()["id"] == entry_id

def test_ingest_empty_notes_location_companions(client):
    """F2 Boundary Test 4: Omit optional fields or submit them empty."""
    files = {"file": ("test.wav", b"data")}
    data = {
        "local_capture_time": "2026-06-06T12:00:00Z",
        "mood": "",
        "location": "",
        "companions": "",
        "notes": ""
    }
    resp = client.post("/api/entries", files=files, data=data)
    assert resp.status_code == 200
    entry = resp.json()
    assert entry["context"]["mood"] == ""
    assert entry["context"]["location"] == ""
    # Should parse to empty list or empty representation
    assert entry["context"]["companions"] == []
    assert entry["context"]["notes"] == ""

def test_ingest_extremely_large_metadata(client):
    """F2 Boundary Test 5: Ingest with massive notes content and many companions."""
    large_notes = "A" * 10000  # 10KB string
    large_companions = ",".join([f"friend_{i}" for i in range(100)])
    
    files = {"file": ("test.wav", b"data")}
    data = {
        "local_capture_time": "2026-06-06T12:00:00Z",
        "companions": large_companions,
        "notes": large_notes
    }
    resp = client.post("/api/entries", files=files, data=data)
    assert resp.status_code == 200
    entry = resp.json()
    assert len(entry["context"]["notes"]) == 10000
    assert len(entry["context"]["companions"]) == 100
