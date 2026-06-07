# E2E Test Infra: Sonochron

## Test Philosophy
- **Opaque-box, requirement-driven**: Tests do not depend on the internal implementation design of Sonochron but verify compliance with the specified API contracts and CLI behaviors.
- **Methodology**: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Interaction + Workload Testing.
- **Verification Strategy**:
  - Verify all happy paths (Tier 1) for features F1, F2, F3, F4.
  - Verify boundary, edge-case, and error handling behaviors (Tier 2).
  - Verify cross-feature interaction / integration scenarios (Tier 3).
  - Verify real-world workload scenarios representing user journeys (Tier 4).

## Feature Inventory
| # | Feature | Source (requirement) | Tier 1 | Tier 2 | Tier 3 |
|---|---------|---------------------|:------:|:------:|:------:|
| 1 | Chronological timeline and browsing (F1) | PROJECT.md §Timeline API | 5 | 5 | ✓ |
| 2 | Audio Capture & Ingestion API (F2) | PROJECT.md §Ingestion API | 5 | 5 | ✓ |
| 3 | Ingest Processing Pipeline (F3) | PROJECT.md §Processing Pipeline | 5 | 5 | ✓ |
| 4 | Vector Search & CLI Index Rebuild (F4) | PROJECT.md §Search API / CLI | 5 | 5 | ✓ |

## Test Architecture
- **Test Runner**: Python `pytest` framework. Executed with `pytest tests/` or `python -m pytest tests/`.
- **Test Client**: Pytest fixtures defined in `tests/conftest.py` that read the environment variable `BASE_URL`.
  - If `BASE_URL` is set, calls are routed to a live server via `httpx.Client(base_url=BASE_URL)`.
  - If `BASE_URL` is not set, calls are routed to a local mock backend client (`tests/mock_backend.py`) for offline and local testing.
- **Directory Layout**:
  - `tests/`
    - `conftest.py` - Fixtures for mock db connection, API client, environment variables.
    - `mock_backend.py` - FastAPI application simulating database state, ingestion, processing pipelines, timeline, and search APIs.
    - `mock_cli.py` - Simulation of the index rebuild CLI (`python -m tests.mock_cli rebuild-index`).
    - `tier1_feature_coverage/` - Happy-path coverage (5 tests per feature, 20 total).
    - `tier2_boundaries/` - Boundary and error handling (5 tests per feature, 20 total).
    - `tier3_combinations/` - Cross-feature pairwise interactions (4 tests total).
    - `tier4_real_world/` - User workloads/scenarios (5 tests total).

## Real-World Application Scenarios (Tier 4)
1. **A Day of Recording**: Multi-entry creation at different times throughout the day, validating chronological grouping and asset storage.
2. **Search & Discover Memory**: Ingestion of a recording, waiting for pipeline to complete, and performing semantic searches matching transcripts or notes.
3. **Timeline Navigation & Playback**: Grouping diary entries by year/month archives, retrieving details of specific entries, and verifying assets.
4. **Recovering from Index Corruption**: Rebuilding the vector search index using the CLI script and verifying that search remains fully functional.
5. **High-Volume Capture & Bulk Review**: Ingesting a large volume of entries, executing parallel pipeline updates, checking timeline aggregation, and rebuilding search indices.

## Coverage Thresholds
- Tier 1: 5 tests per feature (Total: 20)
- Tier 2: 5 tests per feature (Total: 20)
- Tier 3: 4 cross-feature interaction tests (Total: 4)
- Tier 4: 5 real-world scenarios (Total: 5)
- **Total Test Cases**: 49
