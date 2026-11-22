#!/usr/bin/env python3
"""Create the deterministic HACS integration archive for Velotric E-Bike."""

from __future__ import annotations

import argparse
import stat
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_EXCLUDED_DIRECTORIES = {"__pycache__"}
_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


class HacsPackageBuilder:
    """Build a HACS-compatible integration archive."""

    _EXCLUDED_DIRECTORIES = {"__pycache__", "brand", ".git"}
    _EXCLUDED_SUFFIXES = {".pyc", ".pyo"}

    def __init__(self, source: Path, output: Path, include_docs: bool = True):
        self.source = source
        self.output = output
        self.include_docs = include_docs

    def _collect_files(self) -> list[Path]:
        files: list[Path] = []
        # Resolve to absolute path to get the integration name correctly
        resolved_source = self.source.resolve()
        integration_dir = resolved_source / "custom_components" / resolved_source.name

        # Core integration files
        if integration_dir.is_dir():
            for path in integration_dir.rglob("*"):
                relative = path.relative_to(integration_dir)

                # Skip excluded directories/symlinks
                if any(part in self._EXCLUDED_DIRECTORIES or part.startswith(".") for part in relative.parts):
                    continue
                if path.is_symlink():
                    raise SystemExit(f"runtime package cannot contain a symbolic link: {relative.as_posix()}")

                # Skip non-regular files
                if not path.is_file():
                    continue

                # Skip compiled Python files
                if path.suffix in self._EXCLUDED_SUFFIXES:
                    continue

                files.append(path)

        # Include documentation and HACS config files from the project root
        if self.include_docs:
            for doc_name in {"README.md", "hacs.json", "hacs.yaml"}:
                doc_path = self.source / doc_name
                if doc_path.is_file():
                    files.append(doc_path)
        # Sort: core files first (under custom_components/<domain>/), then docs at root
        files.sort(key=lambda path: (
            0 if path.resolve().is_relative_to(self.source.resolve() / "custom_components") else 1,
            str(path)
        ))
        return files

    @staticmethod
    def _archive_name(project_root: Path, path: Path) -> str:
        """Return the archive name for a file."""
        if path.name in {"README.md", "hacs.json", "hacs.yaml"}:
            return path.name
        # Resolve both to absolute paths for comparison
        project_root = project_root.resolve()
        path_abs = path.resolve()
        rel = path_abs.relative_to(project_root)
        parts = rel.parts
        if len(parts) >= 2 and parts[0] == "custom_components":
            return rel.as_posix()
        # If not under custom_components, compute relative path from project root
        return rel.as_posix()

    def _add_to_archive(self, archive: ZipFile, path: Path, archive_name: str) -> None:
        info = ZipInfo(archive_name, _TIMESTAMP)
        info.compress_type = ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        info.extra = b""
        info.comment = b""
        archive.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)

    def build(self) -> str:
        files = self._collect_files()

        required = {"__init__.py", "manifest.json"}
        # Separate core files from docs
        core_files = [path for path in files if path.name not in {"README.md", "hacs.json", "hacs.yaml"}]
        # Check required files exist in the integration directory
        integration_files = {path.name for path in core_files}
        missing = required - integration_files
        if missing:
            names = ", ".join(sorted(missing))
            raise SystemExit(f"runtime package is missing: {names}")

        self.output.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(self.output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            archive.comment = b""
            for path in files:
                archive_name = HacsPackageBuilder._archive_name(self.source, path)
                self._add_to_archive(archive, path, archive_name)

        digest = sha256(self.output.read_bytes()).hexdigest()
        self.output.with_suffix(f"{self.output.suffix}.sha256").write_text(f"{digest}  {self.output.name}\n", encoding="ascii")
        return digest

    @staticmethod
    def verify(source: Path, archive_path: Path) -> None:
        root = source.parent
        expected = {}
        resolved_source = source.resolve()
        integration_dir = resolved_source / "custom_components" / resolved_source.name

        # Core integration files
        if integration_dir.is_dir():
            for path in integration_dir.rglob("*"):
                relative = path.relative_to(integration_dir)
                # Skip excluded directories
                if any(p in HacsPackageBuilder._EXCLUDED_DIRECTORIES or p.startswith(".") for p in relative.parts):
                    continue
                if path.is_file() and path.suffix not in HacsPackageBuilder._EXCLUDED_SUFFIXES:
                    archive_name = HacsPackageBuilder._archive_name(resolved_source, path)
                    if archive_name is not None:
                        expected[archive_name] = path

        # Docs: README.md and hacs.json at root of the zip
        for doc_name in {"README.md", "hacs.json", "hacs.yaml"}:
            doc_path = root / doc_name
            if doc_path.is_file():
                expected[doc_name] = doc_path

        with ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]

            expected_core = {k: v for k, v in expected.items() if k.startswith("custom_components/")}
            expected_root = {k: v for k, v in expected.items() if k not in expected_core}

            if names != sorted(list(expected_core.keys()) + list(expected_root.keys())):
                raise SystemExit(f"runtime package entries differ from source: expected {sorted(list(expected_core.keys()) + list(expected_root.keys()))}, got {sorted(names)}")

            for info in infos:
                filename = info.filename
                if filename in expected_core:
                    path = expected_core[filename]
                elif filename in expected_root:
                    path = expected_root[filename]
                else:
                    raise SystemExit(f"unexpected file in archive: {filename}")

                mode = info.external_attr >> 16
                if (
                    info.date_time != _TIMESTAMP
                    or info.create_system != 3
                    or stat.S_IFMT(mode) != stat.S_IFREG
                    or stat.S_IMODE(mode) != 0o644
                    or info.extra
                    or info.comment
                ):
                    raise SystemExit(f"runtime package metadata is invalid: {filename}")
                if archive.read(info) != path.read_bytes():
                    raise SystemExit(f"runtime package content differs from source: {filename}")


def build_archive(source: Path, output: Path) -> str:
    builder = HacsPackageBuilder(source, output, include_docs=True)
    return builder.build()


def verify_archive(source: Path, archive_path: Path) -> None:
    HacsPackageBuilder.verify(source, archive_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--verify-archive", type=Path)
    args = parser.parse_args()
    if args.verify_archive is not None:
        verify_archive(args.source, args.verify_archive)
        return 0
    assert args.output is not None
    print(build_archive(args.source, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())