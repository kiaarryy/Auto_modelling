from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from adapters.site_a.common import adapt_csv


def test_adapter_maps_units_and_writes_qa_and_provenance(tmp_path: Path) -> None:
    raw = tmp_path / "raw.csv"
    pd.DataFrame(
        {
            "DateTime": ["2024-01-01 00:00", "2024-01-01 00:05"],
            "flow_lps": [1.5, 2.0],
            "power_kw": [3.0, 4.0],
        }
    ).to_csv(raw, index=False)
    config = tmp_path / "mapping.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "source_csv": "raw.csv",
                "timestamp": "DateTime",
                "columns": {
                    "flow_kg_s": {"source": "flow_lps", "scale": 1.0, "unit": "kg/s"},
                    "power_W": {"source": "power_kw", "scale": 1000.0, "unit": "W"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    output = tmp_path / "prepare" / "canonical.csv"
    result = adapt_csv(config, tmp_path, output)

    canonical = pd.read_csv(output)
    assert canonical["flow_kg_s"].tolist() == [1.5, 2.0]
    assert canonical["power_W"].tolist() == [3000.0, 4000.0]
    assert (output.parent / "adapter_qa.csv").exists()
    provenance = json.loads((output.parent / "source_mapping.json").read_text(encoding="utf-8"))
    assert provenance["source_csv"].endswith("raw.csv")
    assert result.rows == 2
    qa = pd.read_csv(output.parent / "adapter_qa.csv")
    assert qa.loc[qa["check"] == "duplicate_timestamps", "status"].iloc[0] == "pass"


def test_adapter_reports_duplicate_timestamp(tmp_path: Path) -> None:
    raw = tmp_path / "raw.csv"
    pd.DataFrame({"DateTime": ["2024-01-01", "2024-01-01"], "value": [1, 2]}).to_csv(raw, index=False)
    config = tmp_path / "mapping.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "source_csv": "raw.csv",
                "timestamp": "DateTime",
                "columns": {"value": {"source": "value", "scale": 1.0}},
            }
        ),
        encoding="utf-8",
    )

    output = tmp_path / "prepare" / "canonical.csv"
    adapt_csv(config, tmp_path, output)
    qa = pd.read_csv(output.parent / "adapter_qa.csv")

    assert qa.loc[qa["check"] == "duplicate_timestamps", "value"].iloc[0] == 1
    assert qa.loc[qa["check"] == "duplicate_timestamps", "status"].iloc[0] == "review"
