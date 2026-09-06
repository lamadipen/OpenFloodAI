"""Keep intake copy clear while preserving submitted fields and privacy defaults."""

from html.parser import HTMLParser
from pathlib import Path


class IntakePanel(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.controls: dict[str, dict[str, str | None]] = {}

    def handle_data(self, data: str) -> None:
        self.text.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        name = attributes.get("name")
        if tag in {"input", "select", "textarea"} and name:
            self.controls[name] = attributes


def intake_panel() -> IntakePanel:
    html = (Path(__file__).resolve().parents[2] / "tools/openfloodai-home-ui.html").read_text()
    panel = html.split('<section id="videoFormPanel"', 1)[1].split("</section>", 1)[0]
    parser = IntakePanel()
    parser.feed("<section " + panel + "</section>")
    return parser


def test_video_intake_uses_plain_language_and_explains_manifest() -> None:
    panel = intake_panel()
    text = " ".join("".join(panel.text).split())
    for expected in (
        "Add Video To Site",
        "This copies the video into the selected site folder and updates manifest.jsonl, "
        "which tracks video details. It does not upload the video or make it public.",
        "Video purpose *",
        "Dataset group *",
        "Difficult case type",
        "Video notes *",
        "Safe to share in repository (keep unchecked by default)",
        "Replace existing video or manifest row",
    ):
        assert expected in text
    assert panel.controls["notes"]["placeholder"] == (
        "Short note about this video, such as what is visible, camera quality, or why it is useful."
    )


def test_video_intake_preserves_field_names_and_safe_defaults() -> None:
    panel = intake_panel()
    controls = panel.controls
    assert "has_human_label" not in controls
    text = "".join(panel.text)
    assert "Has human label" not in text
    assert "Human label already added" not in text
    assert set(controls) == {
        "folder_name",
        "video_file",
        "reference_region",
        "video_id",
        "purpose",
        "split",
        "hard_case_type",
        "notes",
        "approved_for_repo",
        "overwrite",
    }
    for name in ("approved_for_repo", "overwrite"):
        assert controls[name]["type"] == "checkbox"
        assert controls[name]["value"] == "true"
        assert "checked" not in controls[name]
    for name in ("folder_name", "video_file", "video_id", "purpose", "split", "notes"):
        assert "required" in controls[name]
