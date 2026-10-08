"""Build, verify and (opt-in) publish a clean dataset release from a frozen curated dataset.

Typical order (see docs/learning/dataset-release.md):

    approve-source / approve-annotation-license / approve-site   record the human approvals
    build                                                          make openfloodai-dataset-vX.Y/
    verify                                                         check checksums, schema, privacy
    upload-hf                                                      optional, private repository only
    kaggle-metadata                                                optional Kaggle mirror metadata

Building never uploads. Nothing is uploaded unless `upload-hf --yes` is run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from openfloodai.curation.common import CurationError
from openfloodai.release import (
    POLICY_FILENAME,
    ReleaseError,
    approve_annotation_license,
    approve_site,
    approve_source,
    build_release,
    verify_release,
)
from openfloodai.release.publish import PublishError, kaggle_metadata, upload_to_huggingface


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    sub = parser.add_subparsers(dest="command", required=True)

    src = sub.add_parser(
        "approve-source", help="Record that a source system's images may be reused."
    )
    src.add_argument("--source-system", required=True)
    src.add_argument("--license-name", required=True)
    src.add_argument("--credit", required=True)
    src.add_argument("--reuse-note", required=True)
    src.add_argument("--approved-by", required=True)

    lic = sub.add_parser(
        "approve-annotation-license", help="Record the license of OpenFloodAI's annotations."
    )
    lic.add_argument("--spdx-id", required=True)
    lic.add_argument("--holder", required=True)
    lic.add_argument("--approved-by", required=True)

    site = sub.add_parser("approve-site", help="Record a site's location rule and privacy review.")
    site.add_argument("--site-id", required=True)
    site.add_argument(
        "--location-mode",
        choices=("generalized", "exact_approved", "omitted"),
        default="generalized",
    )
    site.add_argument("--precision-decimals", type=int, default=1)
    site.add_argument("--reviewed-by", required=True)
    site.add_argument("--faces-reviewed", action="store_true")
    site.add_argument("--license-plates-reviewed", action="store_true")
    site.add_argument("--private-property-reviewed", action="store_true")
    site.add_argument("--notes", default="")
    site.add_argument("--exact-location-approved-by", default="")

    build = sub.add_parser("build", help="Build a release from a frozen dataset version.")
    build.add_argument("--dataset-id", required=True)
    build.add_argument("--dataset-version", type=int, required=True)
    build.add_argument("--release-version", required=True, help="For example v0.1 (draft) or v1.0.")
    build.add_argument("--notes", required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--previous-release", type=Path)
    build.add_argument(
        "--parquet", action="store_true", help="Also write metadata.parquet (needs pyarrow)."
    )

    verify = sub.add_parser("verify", help="Check a built release.")
    verify.add_argument("release_dir", type=Path)
    verify.add_argument("--require-checklist", action="store_true")

    hf = sub.add_parser(
        "upload-hf", help="Upload a verified release to a PRIVATE Hugging Face dataset."
    )
    hf.add_argument("release_dir", type=Path)
    hf.add_argument("--repo-id", required=True)
    hf.add_argument("--yes", action="store_true", help="Confirm that the release may be uploaded.")

    kg = sub.add_parser("kaggle-metadata", help="Write dataset-metadata.json for a Kaggle mirror.")
    kg.add_argument("release_dir", type=Path)
    kg.add_argument("--owner", required=True)
    kg.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    data: Path = args.data_dir
    policy = data / POLICY_FILENAME
    try:
        if args.command == "approve-source":
            approve_source(
                policy,
                source_system=args.source_system,
                license_name=args.license_name,
                credit=args.credit,
                reuse_note=args.reuse_note,
                approved_by=args.approved_by,
            )
            print(f"Recorded approval for source {args.source_system} in {policy}.")
        elif args.command == "approve-annotation-license":
            approve_annotation_license(
                policy, spdx_id=args.spdx_id, holder=args.holder, approved_by=args.approved_by
            )
            print(f"Recorded the annotation license in {policy}.")
        elif args.command == "approve-site":
            approve_site(
                policy,
                site_id=args.site_id,
                location_mode=args.location_mode,
                precision_decimals=args.precision_decimals,
                reviewed_by=args.reviewed_by,
                checks={
                    "faces_reviewed": args.faces_reviewed,
                    "license_plates_reviewed": args.license_plates_reviewed,
                    "private_property_reviewed": args.private_property_reviewed,
                },
                notes=args.notes,
                exact_location_approved_by=args.exact_location_approved_by,
            )
            print(f"Recorded the privacy review and location rule for {args.site_id}.")
        elif args.command == "build":
            manifest = build_release(
                datasets_dir=data / "datasets",
                dataset_id=args.dataset_id,
                dataset_version=args.dataset_version,
                output_dir=args.output_dir,
                release_version=args.release_version,
                notes=args.notes,
                policy_path=policy,
                reference_dir=data / "reference",
                previous_release=args.previous_release,
                write_parquet=args.parquet,
            )
            counts = manifest["counts"]
            print(
                f"Built {args.release_version} ({manifest['channel']}): "
                f"{counts['released']} examples, {counts['rejected']} excluded. "
                "Nothing was uploaded. Next: verify it."
            )
        elif args.command == "verify":
            result = verify_release(args.release_dir, require_checklist=args.require_checklist)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        elif args.command == "upload-hf":
            print(
                json.dumps(
                    upload_to_huggingface(args.release_dir, args.repo_id, confirmed=args.yes),
                    indent=2,
                )
            )
        else:
            args.out.write_text(
                json.dumps(kaggle_metadata(args.release_dir, args.owner), indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"Wrote {args.out}. Upload the identical release files with it.")
    except ReleaseError as error:
        print(f"Cannot build the release: {error}", file=sys.stderr)
        for item in error.details:
            print(f"  - {item['message']}", file=sys.stderr)
        return 1
    except (CurationError, PublishError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
