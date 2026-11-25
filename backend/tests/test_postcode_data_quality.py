"""Data-quality and provenance completeness tests for the local postcode reference dataset."""
from collections import defaultdict
from pathlib import Path

from backend.app.services.postcode_service import DATASET_METADATA, LEGACY_POSTAL_REFERENCES


def _normalize_state(state: str) -> str:
    return "Abuja FCT" if state == "Abuja (FCT)" else state


def test_no_duplicate_postcode_records():
    codes = [r["code"] for r in LEGACY_POSTAL_REFERENCES]
    assert len(codes) == len(set(codes)), "Duplicate postcode codes found in LEGACY_POSTAL_REFERENCES"


def test_100001_reconciled_between_service_and_readme():
    rec_100001 = next((r for r in LEGACY_POSTAL_REFERENCES if r["code"] == "100001"), None)
    assert rec_100001 is not None
    assert rec_100001["state"] == "Lagos"
    assert rec_100001["lga"] == "Ikeja"
    assert "Ikeja" in rec_100001["area"]

    readme_path = Path(__file__).resolve().parents[2] / "README.md"
    readme_text = readme_path.read_text(encoding="utf-8")
    assert "100001` Lagos Island" not in readme_text
    assert "100001` Ikeja Central / Alausa" in readme_text


def test_valid_state_lga_and_nigeria_coordinate_bounds():
    expected_states = set(DATASET_METADATA["states_covered"])
    actual_states = {_normalize_state(r["state"]) for r in LEGACY_POSTAL_REFERENCES}
    assert actual_states == expected_states

    for rec in LEGACY_POSTAL_REFERENCES:
        assert rec.get("state"), f"Missing state for {rec['code']}"
        assert rec.get("lga"), f"Missing lga for {rec['code']}"
        assert rec.get("area"), f"Missing area for {rec['code']}"
        lat = rec.get("lat")
        lng = rec.get("lng")
        assert isinstance(lat, (int, float)) and isinstance(lng, (int, float)), (
            f"Missing or invalid coordinates for {rec['code']}"
        )
        assert 4.0 <= lat <= 14.0, f"Latitude out of Nigeria bounds for {rec['code']}: {lat}"
        assert 2.5 <= lng <= 15.0, f"Longitude out of Nigeria bounds for {rec['code']}: {lng}"


def test_no_unexplained_coordinate_duplication():
    by_coord = defaultdict(list)
    for rec in LEGACY_POSTAL_REFERENCES:
        by_coord[(rec["lat"], rec["lng"])].append(rec)

    for coord, recs in by_coord.items():
        if len(recs) > 1:
            areas = {r["area"] for r in recs}
            lgas = {(r["state"], r["lga"]) for r in recs}
            assert len(areas) == 1 and len(lgas) == 1, (
                f"Unexplained coordinate duplication at {coord}: {[r['code'] for r in recs]}"
            )


def test_dataset_metadata_completeness():
    assert DATASET_METADATA.get("version")
    assert DATASET_METADATA.get("publication_date")
    assert DATASET_METADATA.get("source")
    assert DATASET_METADATA.get("status") == "local_reference"
    assert len(DATASET_METADATA.get("states_covered", [])) == 11
