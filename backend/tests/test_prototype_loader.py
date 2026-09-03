from unittest.mock import patch

import yaml

from app.core.prototype_loader import PrototypeConfig, PrototypeLoader


def _write_prototype(directory, prototype_id, name, display_order=None):
    config = {
        "id": prototype_id,
        "name": name,
        "systemPrompt": "Test prompt",
    }
    if display_order is not None:
        config["displayOrder"] = display_order

    (directory / f"{prototype_id}.yaml").write_text(yaml.safe_dump(config))


def test_prototype_config_defaults_display_order_for_older_files():
    prototype = PrototypeConfig(id="legacy", name="Legacy", systemPrompt="Test prompt")

    assert prototype.displayOrder == 0


def test_get_all_uses_display_order_independent_of_filesystem_order(tmp_path):
    _write_prototype(tmp_path, "third", "Alpha", 2)
    _write_prototype(tmp_path, "second", "Zulu", 1)
    _write_prototype(tmp_path, "first", "Alpha", 1)

    filesystem_order = ["third.yaml", "second.yaml", "first.yaml"]
    with patch("app.core.prototype_loader.os.listdir", return_value=filesystem_order):
        loader = PrototypeLoader(str(tmp_path))

    assert [prototype.id for prototype in loader.get_all()] == [
        "first",
        "second",
        "third",
    ]


def test_twenty_questions_uses_current_reasoning_summary_field():
    prototype = PrototypeLoader().get_prototype("misconception_glassbox")

    assert prototype is not None
    assert prototype.reasoning == {
        "effort": "max",
        "summary": "auto",
        "context": "all_turns",
    }
