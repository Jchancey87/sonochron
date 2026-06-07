import time

def test_timeline_empty(client):
    """F1 Test 1: Verify timeline is empty initially."""
    response = client.get("/api/timeline")
    assert response.status_code == 200
    assert response.json() == []

def test_timeline_single_entry(client):
    """F1 Test 2: Ingest one entry and verify it appears in the grouped timeline."""
    files = {"file": ("test.wav", b"fake audio content", "audio/wav")}
    data = {
        "local_capture_time": "2026-06-06T12:00:00Z",
        "mood": "happy",
        "location": "home",
        "companions": "alice,bob",
        "notes": "Had a nice lunch."
    }
    resp = client.post("/api/entries", files=files, data=data)
    assert resp.status_code == 200
    entry_id = resp.json()["id"]

    response = client.get("/api/timeline")
    assert response.status_code == 200
    timeline = response.json()
    assert len(timeline) == 1
    assert timeline[0]["year"] == 2026
    assert len(timeline[0]["months"]) == 1
    assert timeline[0]["months"][0]["month"] == 6
    assert len(timeline[0]["months"][0]["entries"]) == 1
    assert timeline[0]["months"][0]["entries"][0]["id"] == entry_id

def test_timeline_multiple_entries_same_month(client):
    """F1 Test 3: Group multiple entries in the same month in descending order."""
    files1 = {"file": ("test1.wav", b"audio1", "audio/wav")}
    data1 = {"local_capture_time": "2026-06-06T12:00:00Z", "notes": "first"}
    resp1 = client.post("/api/entries", files=files1, data=data1)
    id1 = resp1.json()["id"]

    files2 = {"file": ("test2.wav", b"audio2", "audio/wav")}
    data2 = {"local_capture_time": "2026-06-06T13:00:00Z", "notes": "second"}
    resp2 = client.post("/api/entries", files=files2, data=data2)
    id2 = resp2.json()["id"]

    response = client.get("/api/timeline")
    assert response.status_code == 200
    timeline = response.json()
    entries = timeline[0]["months"][0]["entries"]
    assert len(entries) == 2
    # Sorted descending by time, so second one comes first
    assert entries[0]["id"] == id2
    assert entries[1]["id"] == id1

def test_timeline_multiple_months_and_years(client):
    """F1 Test 4: Group entries across multiple years and months correctly."""
    # 2025-05
    client.post("/api/entries", files={"file": ("1.wav", b"1")}, data={"local_capture_time": "2025-05-10T10:00:00Z"})
    # 2026-06
    client.post("/api/entries", files={"file": ("2.wav", b"2")}, data={"local_capture_time": "2026-06-10T10:00:00Z"})
    # 2026-07
    client.post("/api/entries", files={"file": ("3.wav", b"3")}, data={"local_capture_time": "2026-07-10T10:00:00Z"})

    response = client.get("/api/timeline")
    timeline = response.json()
    
    assert len(timeline) == 2  # 2026, 2025
    assert timeline[0]["year"] == 2026
    assert timeline[1]["year"] == 2025

    # Months for 2026 should be sorted descending: July (7) then June (6)
    months_2026 = timeline[0]["months"]
    assert len(months_2026) == 2
    assert months_2026[0]["month"] == 7
    assert months_2026[1]["month"] == 6

def test_timeline_entry_details_link(client):
    """F1 Test 5: Navigate from timeline to entry details and verify content match."""
    files = {"file": ("test.wav", b"audio", "audio/wav")}
    data = {
        "local_capture_time": "2026-06-06T15:00:00Z",
        "mood": "calm",
        "location": "park",
        "companions": "charlie",
        "notes": "Beautiful park walk."
    }
    resp = client.post("/api/entries", files=files, data=data)
    entry_id = resp.json()["id"]

    # Verify via direct details API
    detail_resp = client.get(f"/api/entries/{entry_id}")
    assert detail_resp.status_code == 200
    details = detail_resp.json()
    assert details["context"]["mood"] == "calm"
    assert details["context"]["location"] == "park"
    assert details["context"]["companions"] == ["charlie"]
    assert details["context"]["notes"] == "Beautiful park walk."
