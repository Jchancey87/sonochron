def test_timeline_invalid_time_format(client):
    """F1 Boundary Test 1: Ingest entry with invalid date format and verify fallback grouping."""
    files = {"file": ("test.wav", b"data")}
    data = {"local_capture_time": "invalid-date-string"}
    resp = client.post("/api/entries", files=files, data=data)
    assert resp.status_code == 200
    
    # Get timeline, it should map it to default (e.g. 2026/6) and not crash
    response = client.get("/api/timeline")
    assert response.status_code == 200
    timeline = response.json()
    assert len(timeline) > 0
    assert timeline[0]["year"] == 2026

def test_timeline_nonexistent_entry(client):
    """F1 Boundary Test 2: Request details for nonexistent entry ID returns 404."""
    response = client.get("/api/entries/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

def test_timeline_extreme_years(client):
    """F1 Boundary Test 3: Verify grouping of historical (1900) and future (2100) dates."""
    client.post("/api/entries", files={"file": ("1900.wav", b"1")}, data={"local_capture_time": "1900-01-01T12:00:00Z"})
    client.post("/api/entries", files={"file": ("2100.wav", b"2")}, data={"local_capture_time": "2100-12-31T12:00:00Z"})

    response = client.get("/api/timeline")
    timeline = response.json()
    
    # Sorted descending, so 2100 should be first, 1900 last
    assert timeline[0]["year"] == 2100
    assert timeline[-1]["year"] == 1900

def test_timeline_large_number_of_entries_same_month(client):
    """F1 Boundary Test 4: Verify performance and sorting with 50 entries in same month."""
    for i in range(50):
        # Stagger capture times to ensure order
        cap_time = f"2026-06-06T12:{i:02d}:00Z"
        client.post(
            "/api/entries",
            files={"file": (f"{i}.wav", b"data")},
            data={"local_capture_time": cap_time, "notes": f"Note {i}"}
        )
        
    response = client.get("/api/timeline")
    entries = response.json()[0]["months"][0]["entries"]
    assert len(entries) == 50
    # The first one should be Note 49
    assert entries[0]["context"]["notes"] == "Note 49"
    # The last one should be Note 0
    assert entries[-1]["context"]["notes"] == "Note 0"

def test_timeline_timezone_offset_handling(client):
    """F1 Boundary Test 5: Verify date grouping with various timezone offsets."""
    client.post("/api/entries", files={"file": ("offset1.wav", b"1")}, data={"local_capture_time": "2026-06-06T12:00:00+05:30"})
    client.post("/api/entries", files={"file": ("offset2.wav", b"2")}, data={"local_capture_time": "2026-06-06T12:00:00-08:00"})

    response = client.get("/api/timeline")
    assert response.status_code == 200
    timeline = response.json()
    # Check that both are grouped under 2026/6
    assert timeline[0]["year"] == 2026
    assert timeline[0]["months"][0]["month"] == 6
    assert len(timeline[0]["months"][0]["entries"]) == 2
