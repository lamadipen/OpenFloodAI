from openfloodai import __version__


def test_package_exposes_version() -> None:
    assert __version__ == "5.0.0"
