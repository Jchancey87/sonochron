import os
import sys
import uuid
import wave
import math
import struct
import shutil
from datetime import datetime

# Add backend directory to sys.path to resolve imports correctly
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Force SQLite test database
os.environ["DATABASE_URL"] = "sqlite:///tests/test_sonochron.db"

# Remove old test database and Qdrant storage if they exist
db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_sonochron.db"))
if os.path.exists(db_path):
    print(f"Removing existing test DB: {db_path}")
    os.remove(db_path)

qdrant_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_qdrant_storage"))
if os.path.exists(qdrant_path):
    print(f"Removing existing test Qdrant storage: {qdrant_path}")
    shutil.rmtree(qdrant_path)

# Import backend modules after setting env var
from app.database import init_db, engine, DiaryEntry, EntryContext, SampleAsset, get_or_create_month_archive
from sqlmodel import Session, select
import app.search

# Force Qdrant client redirection to tests/test_qdrant_storage
original_get_client = app.search._get_client
app.search._get_client = lambda storage_path="tests/test_qdrant_storage": original_get_client("tests/test_qdrant_storage")

def generate_wav_file(filepath: str, duration_sec: float = 2.0):
    """Write a valid mono 16-bit PCM WAV file with a sine wave."""
    sample_rate = 22050
    num_samples = int(sample_rate * duration_sec)
    
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with wave.open(filepath, 'w') as wav_file:
        wav_file.setparams((1, 2, sample_rate, num_samples, 'NONE', 'not compressed'))
        for i in range(num_samples):
            # 440Hz sine wave
            value = int(32767.0 * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
            data = struct.pack('<h', value)
            wav_file.writeframesraw(data)
    print(f"Generated WAV file at {filepath} (size: {os.path.getsize(filepath)} bytes)")

def main():
    print("Initializing test database...")
    init_db()
    
    print("Ensuring Qdrant collections...")
    app.search.ensure_collections("tests/test_qdrant_storage")
    
    # Define audio file location (relative to backend/storage/raw/ or absolute)
    # The pipeline resolves relative paths by prefixing backend/storage/raw/
    audio_filename = "verify_test_audio.wav"
    raw_storage_dir = os.path.abspath(os.path.join(backend_dir, "storage", "raw"))
    audio_filepath = os.path.join(raw_storage_dir, audio_filename)
    
    print(f"Creating mock WAV file at {audio_filepath}...")
    generate_wav_file(audio_filepath, duration_sec=2.0)
    
    entry_id = uuid.uuid4()
    dt = datetime.utcnow()
    
    print("Inserting DiaryEntry, EntryContext, and SampleAsset...")
    with Session(engine) as session:
        month_arch = get_or_create_month_archive(session, dt)
        session.commit()
        
        entry = DiaryEntry(
            id=entry_id,
            local_capture_time=dt,
            title="Pipeline Verification Run",
            stage="uploaded",
            month_archive_id=month_arch.id
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)
        
        context = EntryContext(
            entry_id=entry_id,
            mood="focused",
            location="office",
            companions=["teamwork"],
            notes="Testing live ML pipeline execution and database/Qdrant storage integration."
        )
        asset = SampleAsset(
            entry_id=entry_id,
            filename=audio_filename,
            filepath=audio_filename,
            byte_size=os.path.getsize(audio_filepath),
            duration_ms=2000
        )
        session.add(context)
        session.add(asset)
        session.commit()
        
        print(f"Inserted entry {entry_id} in stage '{entry.stage}'")
    
    print("Running real pipeline runner _run_pipeline...")
    from app.pipeline import _run_pipeline
    _run_pipeline(entry_id)
    
    print("Verifying pipeline results...")
    with Session(engine) as session:
        updated_entry = session.get(DiaryEntry, entry_id)
        assert updated_entry is not None, "Entry not found in DB after running pipeline"
        print(f"Final entry stage in DB: {updated_entry.stage}")
        assert updated_entry.stage == "ready", f"Expected stage 'ready', got '{updated_entry.stage}'"
        
        updated_context = session.exec(
            select(EntryContext).where(EntryContext.entry_id == entry_id)
        ).first()
        print(f"Final context notes in DB:\n{updated_context.notes}")
        
        # Verify Whisper transcript is computed (non-empty if speech found, or whatever was computed)
        # Note: Whisper may return empty string for sine wave. We check if the process completed successfully
        # without failing the entry.
        print("Whisper transcription completed successfully.")
        
    print("Checking Qdrant index vectors...")
    client = app.search._get_client("tests/test_qdrant_storage")
    
    # Retrieve text collection point
    text_points = client.retrieve(
        collection_name=app.search.TEXT_COLLECTION,
        ids=[str(entry_id)],
        with_vectors=True
    )
    assert len(text_points) == 1, "Point not found in text collection"
    text_vector = text_points[0].vector["text"]
    print(f"Text vector dimensions: {len(text_vector)}")
    assert len(text_vector) == 384, f"Expected 384 dimensions, got {len(text_vector)}"
    assert any(x != 0.0 for x in text_vector), "Text vector is all zeros (fallback)"
    
    # Retrieve audio collection point
    audio_points = client.retrieve(
        collection_name=app.search.AUDIO_COLLECTION,
        ids=[str(entry_id)],
        with_vectors=True
    )
    assert len(audio_points) == 1, "Point not found in audio collection"
    audio_vector = audio_points[0].vector["audio"]
    print(f"Audio vector dimensions: {len(audio_vector)}")
    assert len(audio_vector) == 1024, f"Expected 1024 dimensions, got {len(audio_vector)}"
    assert any(x != 0.0 for x in audio_vector), "Audio vector is all zeros (fallback)"
    
    print("✅ Live pipeline verification succeeded!")

if __name__ == "__main__":
    main()
