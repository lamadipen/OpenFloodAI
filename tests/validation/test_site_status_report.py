from pathlib import Path

from openfloodai.validation.site_status import read_validation_site_status


def test_status_reads_latest_report_counts_and_review_images(tmp_path: Path) -> None:
    site_dir = tmp_path / "example-site"
    report_path = site_dir / "outputs" / "video-001" / "validation-report.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "\n".join(
            [
                "# Site Validation Report",
                "",
                "- Agree: 2",
                "- Disagree: 1",
                "- Cannot compare: 3",
            ]
        ),
        encoding="utf-8",
    )
    review_images = report_path.parent / "review-images"
    review_images.mkdir()

    status = read_validation_site_status(site_dir)

    assert status.latest_report_counts == {
        "agree": 2,
        "disagree": 1,
        "cannot_compare": 3,
    }
    assert status.review_images_path == str(review_images)


def test_status_explains_missing_site_items(tmp_path: Path) -> None:
    status = read_validation_site_status(tmp_path / "empty-site")

    assert status.next_steps == [
        "Add a site config under configs/.",
        "Add video files under inputs/videos/.",
        "Machine review can still run, but human comparison needs labels.",
        "Add manifest.jsonl so videos can be tracked clearly.",
        "Run validation to create the first report.",
    ]
    assert status.to_dict()["next_steps"] == status.next_steps
