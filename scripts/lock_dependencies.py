"""Snapshot only this project's installed dependency closure, not unrelated packages."""
from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def main() -> None:
    pending = ["langgraph", "pydantic", "httpx", "python-dotenv", "pytest", "setuptools"]
    locked = {}
    while pending:
        name = canonicalize_name(pending.pop())
        if name in locked:
            continue
        dist = distribution(name)
        locked[name] = dist.version
        for raw in dist.requires or []:
            requirement = Requirement(raw)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    header = "# Verified dependency snapshot : CPython 3.10.5 / Windows\n"
    header += "# Regenerate after intentional dependency upgrades ; includes test and build dependencies.\n"
    Path("requirements.lock.txt").write_text(header + "".join(
        f"{name}=={version}\n" for name, version in sorted(locked.items())), encoding="utf-8")
    print("dependency lock written : packages = " + str(len(locked)))


if __name__ == "__main__":
    main()
