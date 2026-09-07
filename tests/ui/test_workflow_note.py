"""The Home UI explains optional human comparison before users reach the forms."""

from html.parser import HTMLParser
from pathlib import Path


class VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def test_home_ui_explains_both_validation_routes_before_forms() -> None:
    html = (Path(__file__).resolve().parents[2] / "tools/openfloodai-home-ui.html").read_text()
    position = html.index('<section id="validationWorkflowNote"')
    panel = html[position:].split("</section>", 1)[0]
    parser = VisibleText()
    parser.feed(panel)
    text = " ".join(" ".join(parser.parts).split())
    for expected in (
        "Human labels are optional for running validation, but required if you want to "
        "compare the machine result with human review.",
        "Route 1: Machine-only review",
        "Needs: site config + video + watched area.",
        "Result: machine evidence only.",
        "No human comparison is possible without a human label.",
        "Route 2: Human comparison review",
        "Needs: site config + video + watched area + human label + manifest.",
        "Result: compares what the machine saw with what the human saw.",
    ):
        assert expected in text
    for form in ("setupForm", "videoFormPanel", "labelFormPanel"):
        assert position < html.index(f'<section id="{form}"')
    assert "display: none" not in panel


def test_workflow_note_is_collapsible_and_not_hidden_in_classic_view() -> None:
    html = (Path(__file__).resolve().parents[2] / "tools/openfloodai-home-ui.html").read_text()
    note = html.split('<section id="validationWorkflowNote"', 1)[1].split("</section>", 1)[0]
    assert "<details>" in note
    assert "<details open>" not in note
    assert '<summary id="validationWorkflowHeading"' in note
    assert "</summary>" in note
    assert "</details>" in note
    assert 'body[data-view="classic"] #validationWorkflowNote' not in html
    assert 'body[data-view="guided"] #validationWorkflowNote' not in html
