import uuid

def test_ingest_minimal(client):
    """F2 Test 1: Ingest entry with only required fields."""
    files = {"file": ("audio.wav", b"riff...", "audio/wav")}
    data = {"local_capture_time": "2026-06-06T12:00:00Z"}
    resp = client.post("/api/entries", files=files, data=data)
    assert resp.status_code == 200
    entry = resp.json()
    assert "id" in entry
    assert entry["local_capture_time"] == "2026-06-06T12:00:00Z"
    assert entry["stage"] == "uploaded"

def test_ingest_all_fields(client):
    """F2 Test 2: Ingest entry with all optional fields."""
    files = {"file": ("recording.mp3", b"mpeg...", "audio/mp3")}
    data = {
        "local_capture_time": "2026-06-06T12:30:00Z",
        "mood": "energetic",
        "location": "gym",
        "companions": "trainer, bob",
        "notes": "Leg day workout"
    }
    resp = client.post("/api/entries", files=files, data=data)
    assert resp.status_code == 200
    entry = resp.json()
    assert entry["context"]["mood"] == "energetic"
    assert entry["context"]["location"] == "gym"
    assert entry["context"]["companions"] == ["trainer", "bob"]
    assert entry["context"]["notes"] == "Leg day workout"
    assert entry["asset"]["filename"] == "recording.mp3"

def test_ingest_idempotency_new(client):
    """F2 Test 3: Ingest with a new idempotency key."""
    key = str(uuid.uuid4())
    files = {"file": ("audio.wav", b"data", "audio/wav")}
    data = {"local_capture_time": "2026-06-06T12:00:00Z"}
    resp = client.post("/api/entries", files=files, data=data, headers={"X-Idempotency-Key": key})
    assert resp.status_code == 200
    assert "id" in resp.json()

def test_ingest_idempotency_duplicate(client):
    """F2 Test 4: Ingest with duplicate idempotency key returns cached entry."""
    key = str(uuid.uuid4())
    files1 = {"file": ("audio1.wav", b"data1", "audio/wav")}
    data1 = {"local_capture_time": "2026-06-06T12:00:00Z", "notes": "first upload"}
    resp1 = client.post("/api/entries", files=files1, data=data1, headers={"X-Idempotency-Key": key})
    assert resp1.status_code == 200
    id1 = resp1.json()["id"]

    files2 = {"file": ("audio2.wav", b"data2", "audio/wav")}
    data2 = {"local_capture_time": "2026-06-06T13:00:00Z", "notes": "second upload"}
    resp2 = client.post("/api/entries", files=files2, data=data2, headers={"X-Idempotency-Key": key})
    assert resp2.status_code == 200
    id2 = resp2.json()["id"]

    # Verify same entry was returned
    assert id1 == id2
    assert resp2.json()["context"]["notes"] == "first upload"

def test_ingest_companions_parsing_modes(client):
    """F2 Test 5: Verify support for both comma-separated and JSON list formats in companions."""
    # Test comma-separated string
    resp1 = client.post(
        "/api/entries",
        files={"file": ("1.wav", b"1")},
        data={"local_capture_time": "2026-06-06T12:00:00Z", "companions": "alice, bob, charlie"}
    )
    assert resp1.json()["context"]["companions"] == ["alice", "bob", "charlie"]

    # Test JSON list
    resp2 = client.post(
        "/api/entries",
        files={"file": ("2.wav", b"2")},
        data={"local_capture_time": "2026-06-06T12:00:00Z", "companions": '["dave", "eve"]'}
    )
    assert resp2.json()["context"]["companions"] == ["dave", "eve"]
