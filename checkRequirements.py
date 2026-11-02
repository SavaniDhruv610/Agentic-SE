#!/usr/bin/env python3
"""Check every line of a requirements file against PyPI before running pip install.

Checks are always made against Python 3.11, no matter which Python runs the script.

Usage:
    python checkRequirements.py [requirements.txt]

Needs: pip install packaging
"""
import json
import sys
import urllib.error
import urllib.request

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

PYPI = "https://pypi.org/pypi"
TARGET_PYTHON = "3.11"

_cache = {}


def fetch_json(url):
    """Return parsed JSON, or None if PyPI answers 404. Other errors are raised."""
    if url in _cache:
        return _cache[url]
    req = urllib.request.Request(url, headers={"User-Agent": "requirements-checker/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        data = None
    _cache[url] = data
    return data


def parse_line(raw):
    """Return a parsed requirement, or None for comments and pip options."""
    line = raw.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        return None
    try:
        return Requirement(line)
    except InvalidRequirement as exc:
        raise ValueError(f"Invalid requirement line: {raw.rstrip()}") from exc


def min_python(spec):
    """Highest lower bound found in a SpecifierSet (e.g. '>=3.8,<4' -> Version('3.8'))."""
    lows = []
    for s in spec:
        if s.operator in (">=", ">", "~=", "==", "==="):
            try:
                lows.append(Version(s.version.rstrip(".*")))
            except InvalidVersion:
                pass
    return max(lows) if lows else None


def release_for(requirement, project):
    """Choose the newest PyPI release satisfying the requirement, if any."""
    specifier = requirement.specifier
    if not str(specifier):
        return project["info"]["version"]

    versions = []
    for version in project.get("releases", {}):
        try:
            parsed = Version(version)
        except InvalidVersion:
            continue
        if specifier.contains(parsed, prereleases=True):
            versions.append(parsed)
    return str(max(versions)) if versions else None


def main(path):
    checked = 0
    not_found = []      # package missing OR no matching release
    incompatible = []   # exists, but requires_python excludes 3.11
    highest = None      # (min_version, name, version)

    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    for raw in lines:
        try:
            requirement = parse_line(raw)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
        if requirement is None:
            continue
        checked += 1
        name = requirement.name

        project = fetch_json(f"{PYPI}/{name}/json")
        if project is None:
            not_found.append(f"{name} (package does not exist)")
            continue

        version = release_for(requirement, project)
        if version is None:
            not_found.append(f"{name} (no release matches {requirement.specifier})")
            continue

        data = fetch_json(f"{PYPI}/{name}/{version}/json")
        if data is None:
            not_found.append(f"{name}=={version} (version does not exist)")
            continue
        label = f"{name}=={version}"

        req = (data["info"].get("requires_python") or "").strip()
        if not req:
            continue  # no requires_python -> counts as compatible

        try:
            spec = SpecifierSet(req)
        except InvalidSpecifier as exc:
            raise ValueError(
                f"Invalid requires_python from PyPI for {label}: {req!r}"
            ) from exc

        if not spec.contains(TARGET_PYTHON, prereleases=True):
            incompatible.append(f"{label} (requires Python {req})")

        low = min_python(spec)
        if low is not None and (highest is None or low > highest[0]):
            highest = (low, label, req)

    print(f"Dependencies checked: {checked}")
    print(f"Not found on PyPI: {len(not_found)}")
    for item in not_found:
        print(f"  {item}")
    print(f"Incompatible with Python {TARGET_PYTHON}: {len(incompatible)}")
    for item in incompatible:
        print(f"  {item}")
    if highest:
        low, label, _ = highest
        print(f"Highest requirement: {label} (>={low})")
    else:
        print("Highest requirement: none")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "requirements.txt")