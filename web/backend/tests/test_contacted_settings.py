import io
import os
import sys
from pathlib import Path
import pandas as pd
import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import core.config
from main import app
from core.auth import get_current_user


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir(parents=True)

    monkeypatch.setattr(core.config, "GLOBAL_CONTACTED_DIR", data_dir)
    monkeypatch.setattr(core.config, "GLOBAL_ANALYSIS_DIR", analysis_dir)
    monkeypatch.setattr(core.config, "COMPARISON_REPORT_XLSX", analysis_dir / "contacted_hr_vs_ai_comparison.xlsx")
    monkeypatch.setattr(core.config, "COMPARISON_REPORT_CSV", analysis_dir / "contacted_hr_vs_ai_comparison.csv")
    monkeypatch.delenv("CONTACTED_CANDIDATES_PATH", raising=False)

    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "email": "test@example.com",
        "full_name": "Test Admin",
        "role": "admin",
    }
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def test_contacted_settings_lifecycle(client, tmp_path):
    # 1. Initially not configured
    res = client.get("/api/settings/contacted-candidates")
    assert res.status_code == 200
    data = res.json()
    assert data["configured"] is False
    assert data["total_names"] == 0

    # 2. Upload sample excel
    df = pd.DataFrame({
        "Candidate Name": ["Yiğit Can Özkaya", "Ayşe Demir"],
        "Status": ["Interviewed", "Rejected"],
        "Notes": ["Strong candidate", "Underqualified"],
    })
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    buf.seek(0)

    upload_res = client.post(
        "/api/settings/contacted-candidates",
        files={"file": ("contacted.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert upload_res.status_code == 200
    upload_data = upload_res.json()
    assert upload_data["configured"] is True
    assert upload_data["total_names"] == 2
    assert "contacted_candidates.xlsx" in upload_data["filename"]
    assert "CONTACTED_CANDIDATES_PATH" in os.environ

    # 3. Download the uploaded file
    dl_res = client.get("/api/settings/contacted-candidates/download")
    assert dl_res.status_code == 200
    assert len(dl_res.content) > 0

    # 4. Delete the file
    del_res = client.delete("/api/settings/contacted-candidates")
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["configured"] is False
    assert del_data["total_names"] == 0
    assert "CONTACTED_CANDIDATES_PATH" not in os.environ
