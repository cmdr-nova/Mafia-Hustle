import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def project_version():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", project_version())


def test_changelog_has_notes_for_the_current_version():
    # The Release workflow publishes this section, so bumping the version without writing it
    # would leave nothing to release. See RELEASING.md.
    changelog = (ROOT / "CHANGELOG.md").read_text()
    match = re.search(
        rf"^## \[{re.escape(project_version())}\] - \d{{4}}-\d{{2}}-\d{{2}}\n(.*?)(?=^## |\Z)",
        changelog,
        re.MULTILINE | re.DOTALL,
    )
    assert match, f"CHANGELOG.md has no '## [{project_version()}] - YYYY-MM-DD' section"
    assert match.group(1).strip(), "that section is empty"


def test_changelog_keeps_an_unreleased_section():
    assert "## [Unreleased]" in (ROOT / "CHANGELOG.md").read_text()
