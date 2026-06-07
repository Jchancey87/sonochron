import time

def test_pipeline_instant_retrieval(client):
    """F3 Boundary Test 1: Instantly retrieve entry and verify starting stage is 'uploaded'."""
    resp = client.post(
        "/api/entries",
        files={"file": ("test.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:00:00Z"}
    )
    entry_id = resp.json()["id"]
    
    # Instant query (no sleep) should yield 'uploaded' stage
    detail_resp = client.get(f"/api/entries/{entry_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["stage"] == "uploaded"

def test_pipeline_re_entry_processing(client):
    """F3 Boundary Test 2: Verify entry stays in 'ready' state after processing completes."""
    resp = client.post(
        "/api/entries",
        files={"file": ("test.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:00:00Z"}
    )
    entry_id = resp.json()["id"]
    
    # Wait for indexing
    for _ in range(20):
        if client.get(f"/api/entries/{entry_id}").json()["stage"] == "ready":
            break
        time.sleep(0.01)
        
    # Check again later
    time.sleep(0.02)
    assert client.get(f"/api/entries/{entry_id}").json()["stage"] == "ready"

def test_pipeline_fail_keyword_variants(client):
    """F3 Boundary Test 3: Test different fail keyword casing triggers failed stage."""
    variants = ["FAILED", "system failure", "must FAIL immediately"]
    
    for var in variants:
        resp = client.post(
            "/api/entries",
            files={"file": ("test.wav", b"data")},
            data={"local_capture_time": "2026-06-06T12:00:00Z", "notes": var}
        )
        entry_id = resp.json()["id"]
        
        # Wait for processing
        for _ in range(20):
            entry_resp = client.get(f"/api/entries/{entry_id}")
            if entry_resp.json()["stage"] == "failed":
                break
            time.sleep(0.01)
            
        assert entry_resp.json()["stage"] == "failed"

def test_pipeline_recovery_after_failure(client):
    """F3 Boundary Test 4: Can upload corrected entry after a prior entry fails."""
    # First upload fails
    resp1 = client.post(
        "/api/entries",
        files={"file": ("test.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:00:00Z", "notes": "fail"}
    )
    entry_id_1 = resp1.json()["id"]
    
    # Second upload succeeds (different idempotency/notes)
    resp2 = client.post(
        "/api/entries",
        files={"file": ("test.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:00:00Z", "notes": "normal now"}
    )
    entry_id_2 = resp2.json()["id"]
    
    # Wait for processing
    time.sleep(0.05)
    
    assert client.get(f"/api/entries/{entry_id_1}").json()["stage"] == "failed"
    assert client.get(f"/api/entries/{entry_id_2}").json()["stage"] == "ready"

def test_pipeline_empty_file(client):
    """F3 Boundary Test 5: Verify processing of an empty 0-byte file."""
    resp = client.post(
        "/api/entries",
        files={"file": ("empty.wav", b"")},
        data={"local_capture_time": "2026-06-06T12:00:00Z"}
    )
    assert resp.status_code == 422
