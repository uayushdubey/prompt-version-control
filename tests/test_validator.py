import json
import os
import shutil
import tempfile
from promptvc.core.repo import PromptRepo
from promptvc.core.validator import validate_dataset, validate_prompt


def test_validate_dataset_nonexistent():
    res = validate_dataset("nonexistent_file.json")
    assert not res.valid
    assert "does not exist" in res.errors[0]


def test_validate_dataset_invalid_json(tmp_path):
    f = tmp_path / "invalid.json"
    f.write_text("{invalid")
    res = validate_dataset(str(f))
    assert not res.valid
    assert "Invalid JSON" in res.errors[0]


def test_validate_dataset_valid(tmp_path):
    f = tmp_path / "valid.json"
    data = [
        {
            "id": "case-1",
            "input": {"text": "hello"},
            "assertions": [
                {"type": "contains", "value": "hello"}
            ],
            "checks": [
                {"type": "exact_match", "expected": "hello"}
            ],
            "llm_judge": {
                "criteria": "be polite",
                "weight": 0.5
            }
        }
    ]
    f.write_text(json.dumps(data))
    res = validate_dataset(str(f))
    assert res.valid
    assert not res.errors


def test_validate_dataset_invalid_fields(tmp_path):
    f = tmp_path / "invalid_fields.json"
    data = [
        {
            "id": "case-1",
            # missing input
            "assertions": [
                {"type": "unknown_type", "value": "test"}
            ]
        }
    ]
    f.write_text(json.dumps(data))
    res = validate_dataset(str(f))
    assert not res.valid
    assert any("input" in e for e in res.errors)
    assert any("unknown_type" in e for e in res.errors)


def test_validate_prompt(tmp_path):
    # Change CWD or initialize PromptRepo in tmp dir by patching StorageEngine
    # Let's mock PromptRepo metadata to test validate_prompt cleanly
    class MockRepo:
        def get_version_meta(self, name, version):
            if name == "test_prompt":
                return {
                    "prompt": "Hello {{name}}, welcome to {{place}}!"
                }
            raise Exception("not found")

        def get_schema(self, name, version):
            if name == "test_prompt":
                return {
                    "variables": {
                        "name": {"type": "string", "required": True},
                        "place": {"type": "string", "required": False},
                    }
                }
            return {}

    repo = MockRepo()
    res = validate_prompt(repo, "test_prompt", "v1")
    assert res.valid
    assert not res.errors
    assert not res.warnings

    # Test missing var from schema
    class MockRepoMissing:
        def get_version_meta(self, name, version):
            return {"prompt": "Hello {{name}} and {{age}}!"}

        def get_schema(self, name, version):
            return {
                "variables": {
                    "name": {"type": "string", "required": True}
                }
            }

    res2 = validate_prompt(MockRepoMissing(), "test_prompt", "v1")
    assert not res2.valid
    assert any("age" in e for e in res2.errors)
