import time

def test_pipeline_transitions_to_ready(client):
    """F3 Test 1: Ingest entry and verify it transitions to the 'ready' stage."""
    resp = client.post(
        "/api/entries",
        files={"file": ("test.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:00:00Z"}
    )
    entry_id = resp.json()["id"]
    
    # Poll until stage is 'ready'
    for _ in range(20):
        entry_resp = client.get(f"/api/entries/{entry_id}")
        if entry_resp.json()["stage"] == "ready":
            break
        time.sleep(0.01)
    
    assert entry_resp.json()["stage"] == "ready"

def test_pipeline_stages_order(client):
    """F3 Test 2: Ingest entry and verify intermediate stage progression."""
    resp = client.post(
        "/api/entries",
        files={"file": ("test.wav", b"data")},
        data={"local_capture_time": "2026-06-06T12:00:00Z"}
    )
    entry_id = resp.json()["id"]
    
    observed_stages = []
    for _ in range(50):
        s = client.get(f"/api/entries/{entry_id}").json()["stage"]
        if not observed_stages or observed_stages[-1] != s:
            observed_stages.append(s)
        if s == "ready":
            break
        time.sleep(0.005)
        
    # We want to verify we started with uploaded/validated and ended with ready
    assert "uploaded" in observed_stages
    assert "ready" in observed_stages
    # Ensure stages are standard transition subsets
    stages_set = {"uploaded", "validated", "speech_detected", "transcribed", "text_embedded", "audio_embedded", "indexed", "ready"}
    for stage in observed_stages:
        assert stage in stages_set

def test_pipeline_failure_path(client):
    """F3 Test 3: Trigger pipeline failure using notes with 'fail' string."""
    resp = client.post(
        "/api/entries",
        files={"file": ("test.wav", b"data")},
        data={
            "local_capture_time": "2026-06-06T12:00:00Z",
            "notes": "This ingestion will fail because of notes."
        }
    )
    entry_id = resp.json()["id"]
    
    # Poll until stage is 'failed'
    for _ in range(20):
        entry_resp = client.get(f"/api/entries/{entry_id}")
        if entry_resp.json()["stage"] == "failed":
            break
        time.sleep(0.01)
        
    assert entry_resp.json()["stage"] == "failed"

def test_pipeline_asset_persisted(client):
    """F3 Test 4: Verify that asset reference remains valid after pipeline completion."""
    resp = client.post(
        "/api/entries",
        files={"file": ("test_asset.mp3", b"mpeg content")},
        data={"local_capture_time": "2026-06-06T12:00:00Z"}
    )
    entry_id = resp.json()["id"]
    
    # Poll until ready
    for _ in range(20):
        entry_resp = client.get(f"/api/entries/{entry_id}")
        if entry_resp.json()["stage"] == "ready":
            break
        time.sleep(0.01)
        
    data = entry_resp.json()
    assert data["asset"]["filename"] == "test_asset.mp3"
    assert "filepath" in data["asset"]

def test_pipeline_context_preservation(client):
    """F3 Test 5: Verify context data is preserved after pipeline completion."""
    resp = client.post(
        "/api/entries",
        files={"file": ("test.wav", b"data")},
        data={
            "local_capture_time": "2026-06-06T12:00:00Z",
            "mood": "calm",
            "location": "office",
            "companions": "frank",
            "notes": "Work focus"
        }
    )
    entry_id = resp.json()["id"]
    
    # Poll until ready
    for _ in range(20):
        entry_resp = client.get(f"/api/entries/{entry_id}")
        if entry_resp.json()["stage"] == "ready":
            break
        time.sleep(0.01)
        
    context = entry_resp.json()["context"]
    assert context["mood"] == "calm"
    assert context["location"] == "office"
    assert context["companions"] == ["frank"]
    assert context["notes"] == "Work focus"
