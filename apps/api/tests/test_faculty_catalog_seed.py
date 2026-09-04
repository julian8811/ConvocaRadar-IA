"""T1: Faculty catalog seed matches VT - RED test."""

from app.models import Faculty, InstitutionalAxis, FacultyProfile


def test_seed_json_has_correct_counts():
    import json
    from pathlib import Path

    data = json.loads(Path("seed/faculties_axes_v1.json").read_text())
    assert len(data["faculties"]) == 4
    assert len(data["axes"]) == 6
    assert len(data["profiles"]) == 24
    assert len(data["source_urls"]) == 8
    assert data["version"] == 1


def test_seed_faculties_match_vt_names():
    import json
    from pathlib import Path

    data = json.loads(Path("seed/faculties_axes_v1.json").read_text())
    names = {f["name"] for f in data["faculties"]}
    assert names == {
        "Facultad de Administracion",
        "Facultad de Arquitectura e Ingenieria",
        "Facultad de Ciencias de la Salud",
        "Facultad de Ciencias Sociales y Educacion",
    }


def test_seed_axes_match_vt():
    import json
    from pathlib import Path

    data = json.loads(Path("seed/faculties_axes_v1.json").read_text())
    keys = {a["key"] for a in data["axes"]}
    assert keys == {"docencia", "investigacion", "extension", "internacionalizacion", "bienestar", "innovacion"}


def test_models_importable():
    # Validates that new models exist and have expected columns
    assert hasattr(Faculty, "__tablename__")
    assert Faculty.__tablename__ == "faculties"
    assert hasattr(InstitutionalAxis, "__tablename__")
    assert InstitutionalAxis.__tablename__ == "institutional_axes"
    assert hasattr(FacultyProfile, "__tablename__")
    assert FacultyProfile.__tablename__ == "faculty_profiles"


def test_faculty_profile_has_embedding_and_threshold():
    assert hasattr(FacultyProfile, "embedding")
    assert hasattr(FacultyProfile, "threshold")
    assert hasattr(FacultyProfile, "version")
    assert hasattr(FacultyProfile, "source_url")


def test_opportunity_axis_match_model():
    from app.models import OpportunityAxisMatch

    assert OpportunityAxisMatch.__tablename__ == "opportunity_axis_matches"
    assert hasattr(OpportunityAxisMatch, "embedding_score")
    assert hasattr(OpportunityAxisMatch, "final_score")
    assert hasattr(OpportunityAxisMatch, "reasons")


def test_alert_has_faculty_id():
    from app.models import Alert

    assert hasattr(Alert, "faculty_id")


def test_config_flags():
    from app.core.config import get_settings

    s = get_settings()
    assert hasattr(s, "faculty_match_enabled")
    assert hasattr(s, "axis_match_threshold")
