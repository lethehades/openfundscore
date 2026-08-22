from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
_RESOURCE_PREFIX = "openfundscore/_resources/"
_EXPECTED_RESOURCE_SELECTORS = frozenset(
    {
        ("metric-catalog", "openfundscore-category-metrics", "0.1.0"),
        ("peer-admission", "category-profile-buckets", "0.1.0"),
        ("platform-boundary", "ant_fortune", "0.1.0"),
        ("schema", "external_rating", "0.1.0"),
        ("schema", "mainland_official_snapshot", "0.1.0"),
        ("schema", "manager_research", "0.1.0"),
        ("schema", "provider_contract", "0.1.0"),
        ("schema", "provider_contract", "0.2.0"),
        ("schema", "provider_record", "0.1.0"),
        ("schema", "provider_record", "0.2.0"),
        ("schema", "provider_record", "0.3.0"),
        ("schema", "score_evidence_usage", "0.1.0"),
        ("schema", "score_evidence_usage", "0.2.0"),
        ("scoring-config", "openfundscore-core", "0.1.0"),
        ("strategy-mapping", "complex_alternatives", "0.1.0"),
    }
)
_EXPECTED_SELECTORS = _EXPECTED_RESOURCE_SELECTORS
_EXPECTED_RESOURCE_PAYLOADS = frozenset(
    {
        "__init__.py",
        "index.json",
        "metric-catalog/openfundscore-category-metrics/0.1.0.json",
        "peer-admission/category-profile-buckets/0.1.0.json",
        "platform-boundary/ant_fortune/0.1.0.json",
        "schema/external_rating/0.1.0.schema.json",
        "schema/mainland_official_snapshot/0.1.0.schema.json",
        "schema/manager_research/0.1.0.schema.json",
        "schema/provider_contract/0.1.0.schema.json",
        "schema/provider_contract/0.2.0.schema.json",
        "schema/provider_record/0.1.0.schema.json",
        "schema/provider_record/0.2.0.schema.json",
        "schema/provider_record/0.3.0.schema.json",
        "schema/score_evidence_usage/0.1.0.schema.json",
        "schema/score_evidence_usage/0.2.0.schema.json",
        "scoring-config/openfundscore-core/0.1.0.json",
        "strategy-mapping/complex_alternatives/0.1.0.json",
    }
)
_EXPECTED_RESOURCE_FILES = _EXPECTED_RESOURCE_PAYLOADS
_README_DOCUMENT_LINKS = frozenset(
    {
        "docs/PROJECT_CHARTER.md",
        "docs/ROADMAP.md",
        "docs/CANONICAL_DATA_MODEL.md",
        "docs/CATEGORY_METRICS.md",
        "docs/VALIDATION.md",
        "docs/WALK_FORWARD.md",
        "docs/PUBLICATION_GATE.md",
        "docs/PROVIDER_SDK.md",
        "docs/ANT_FORTUNE_BOUNDARY.md",
        "docs/OFFICIAL_PROVIDERS.md",
        "docs/MAINLAND_OFFICIAL_SNAPSHOT.md",
        "docs/FUND_TAXONOMY.md",
        "docs/SCORING_RFC.md",
        "docs/MANAGER_RESEARCH.md",
        "docs/DATA_PROVIDER_POLICY.md",
    }
)
_SDIST_TOP_LEVEL_FILES = frozenset(
    {"LICENSE", "MANIFEST.in", "PKG-INFO", "README.md", "pyproject.toml", "setup.cfg"}
)
_SDIST_EGG_INFO_FILES = frozenset(
    {
        "PKG-INFO",
        "SOURCES.txt",
        "dependency_links.txt",
        "entry_points.txt",
        "requires.txt",
        "top_level.txt",
    }
)
_SENSITIVE_EXACT_NAMES = frozenset(
    {
        ".env",
        "credential.json",
        "credentials.json",
        "secret.json",
        "secrets.json",
    }
)
_PROVIDER_PAYLOAD_JSON = re.compile(
    r"(?:sec|world[-_]?bank|provider)(?:[-_][a-z0-9]+)*[-_]"
    r"(?:fixture|payload|response)\.json"
)
_SECRET_PAYLOAD_PATTERNS = (
    re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
)


def _wheel_resources(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {
            name.removeprefix(_RESOURCE_PREFIX): archive.read(name)
            for name in archive.namelist()
            if name.startswith(_RESOURCE_PREFIX)
        }


def _sdist_resources(path: Path) -> dict[str, bytes]:
    files = _sdist_files(path)
    prefix = "src/" + _RESOURCE_PREFIX
    return {
        name.removeprefix(prefix): payload
        for name, payload in files.items()
        if name.startswith(prefix)
    }


def _sdist_files(path: Path) -> dict[str, bytes]:
    with tarfile.open(path, "r:gz") as archive:
        files: dict[str, bytes] = {}
        for member in archive.getmembers():
            if not member.isfile() or "/" not in member.name:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            relative_name = member.name.split("/", 1)[1]
            files[relative_name] = extracted.read()
        return files


class DistributionResourceTests(unittest.TestCase):
    def test_distribution_name_policy_allows_trusted_synthetic_fixture_module(
        self,
    ) -> None:
        for name in ("LICENSE", "src/openfundscore/fixtures.py"):
            with self.subTest(name=name):
                self.assert_safe_distribution_name(name)

    def test_distribution_name_policy_rejects_raw_fixtures_and_credentials(
        self,
    ) -> None:
        names = (
            "fixtures/sec.json",
            "sec-fixture.json",
            "world-bank-fixture.json",
            "provider_fixture.json",
            "sec-response.json",
            "world_bank_payload.json",
            "provider-response.json",
            ".env",
            ".env.production",
            "credentials.json",
            "private.key",
            "private.pem",
        )
        for name in names:
            with self.subTest(name=name), self.assertRaises(AssertionError):
                self.assert_safe_distribution_name(name)

    def test_distribution_payload_policy_rejects_private_keys_and_real_token_shapes(
        self,
    ) -> None:
        self.assert_safe_distribution_payload(
            b"Documentation may mention API keys and credentials without bundling one."
        )
        for payload in (
            b"-----BEGIN PRIVATE KEY-----\nprivate\n-----END PRIVATE KEY-----",
            b"token=ghp_1234567890abcdefghijklmnopqrstuvwxyz",
            b"AWS_ACCESS_KEY_ID=AKIA1234567890ABCDEF",
        ):
            with self.subTest(payload=payload[:20]), self.assertRaises(AssertionError):
                self.assert_safe_distribution_payload(payload)

    def assert_safe_distribution_name(self, name: str) -> None:
        self.assertFalse(name.startswith("/"))
        self.assertNotIn("\\", name)
        parts = Path(name).parts
        self.assertNotIn("..", parts)
        for index, part in enumerate(parts):
            lowered = part.lower()
            self.assertFalse(index < len(parts) - 1 and lowered == "fixtures")
            self.assertNotIn(lowered, _SENSITIVE_EXACT_NAMES)
            self.assertFalse(lowered.startswith(".env."))
            self.assertIsNone(re.fullmatch(r".*(?:-|_|\.)fixture\.json", lowered))
            self.assertIsNone(_PROVIDER_PAYLOAD_JSON.fullmatch(lowered))
            self.assertFalse(lowered.endswith((".key", ".pem", ".p12", ".pfx")))

    def assert_safe_distribution_payload(self, payload: bytes) -> None:
        for pattern in _SECRET_PAYLOAD_PATTERNS:
            self.assertIsNone(pattern.search(payload))

    def assert_wheel_contract(self, path: Path) -> None:
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                name = member.filename
                with self.subTest(wheel_member=name):
                    self.assert_safe_distribution_name(name)
                    mode = member.external_attr >> 16
                    self.assertFalse(stat.S_ISLNK(mode))
                    file_type = stat.S_IFMT(mode)
                    if member.is_dir():
                        self.assertIn(file_type, {0, stat.S_IFDIR})
                        continue
                    self.assertIn(file_type, {0, stat.S_IFREG})
                    self.assert_safe_distribution_payload(archive.read(name))
                    parts = Path(name).parts
                    self.assertNotIn("docs", {part.lower() for part in parts})
                    self.assertNotIn("tests", {part.lower() for part in parts})
                    self.assertTrue(
                        parts[0] == "openfundscore" or parts[0].endswith(".dist-info")
                    )
                    if Path(name).suffix == ".json" and parts[0] == "openfundscore":
                        self.assertTrue(name.startswith(_RESOURCE_PREFIX))
                        self.assertIn(
                            name.removeprefix(_RESOURCE_PREFIX),
                            _EXPECTED_RESOURCE_FILES,
                        )

    def assert_sdist_document_contract(self, path: Path) -> None:
        with tarfile.open(path, "r:gz") as archive:
            root: str | None = None
            for member in archive.getmembers():
                parts = Path(member.name).parts
                with self.subTest(sdist_archive_member=member.name):
                    self.assertGreaterEqual(len(parts), 1)
                    self.assertFalse(member.name.startswith("/"))
                    self.assertNotIn("\\", member.name)
                    self.assertNotIn("..", parts)
                    root = parts[0] if root is None else root
                    self.assertEqual(parts[0], root)
                    self.assertFalse(member.issym() or member.islnk())
                    self.assertTrue(member.isdir() or member.isfile())
                    if member.isdir() or len(parts) == 1:
                        continue
                    relative_name = "/".join(parts[1:])
                    self.assert_safe_distribution_name(relative_name)
                    relative_parts = Path(relative_name).parts
                    if len(relative_parts) == 1:
                        self.assertIn(relative_name, _SDIST_TOP_LEVEL_FILES)
                    elif relative_parts[0] == "docs":
                        self.assertIn(relative_name, _README_DOCUMENT_LINKS)
                    elif relative_parts[:2] == ("src", "openfundscore.egg-info"):
                        self.assertIn(relative_parts[-1], _SDIST_EGG_INFO_FILES)
                    else:
                        self.assertEqual(relative_parts[:2], ("src", "openfundscore"))
                        self.assertIn(Path(relative_name).suffix, {".py", ".json"})
                        if Path(relative_name).suffix == ".json":
                            prefix = "src/" + _RESOURCE_PREFIX
                            self.assertTrue(relative_name.startswith(prefix))
                            self.assertIn(
                                relative_name.removeprefix(prefix),
                                _EXPECTED_RESOURCE_FILES,
                            )

        files = _sdist_files(path)
        for payload in files.values():
            self.assert_safe_distribution_payload(payload)
        self.assertIn("README.md", files)
        self.assertIn("docs/OFFICIAL_PROVIDERS.md", files)
        readme = files["README.md"].decode("utf-8")
        for target in _README_DOCUMENT_LINKS:
            with self.subTest(target=target):
                self.assertIn(f"]({target})", readme)
                self.assertIn(target, files)

        self.assertEqual(
            frozenset(name for name in files if name.startswith("docs/")),
            _README_DOCUMENT_LINKS,
        )

    def test_sdist_contains_readme_document_targets_without_sensitive_fixtures(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            dist = root / "dist"
            dist.mkdir()
            shutil.copytree(
                ROOT,
                source,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".venv",
                    "__pycache__",
                    "build",
                    "dist",
                    "*.egg-info",
                ),
            )
            builder = root / "builder"
            venv.EnvBuilder(with_pip=True).create(builder)
            builder_python = builder / "bin" / "python"
            clean_environment = os.environ.copy()
            clean_environment.pop("PYTHONPATH", None)
            clean_environment["PYTHONNOUSERSITE"] = "1"
            install_build = subprocess.run(
                [str(builder_python), "-m", "pip", "install", "build>=1.2"],
                check=False,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                install_build.returncode,
                0,
                msg=(f"stdout={install_build.stdout}\nstderr={install_build.stderr}"),
            )
            build = subprocess.run(
                [
                    str(builder_python),
                    "-m",
                    "build",
                    "--sdist",
                    "--outdir",
                    str(dist),
                    str(source),
                ],
                check=False,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                build.returncode,
                0,
                msg=f"stdout={build.stdout}\nstderr={build.stderr}",
            )
            sdists = tuple(dist.glob("openfundscore-*.tar.gz"))
            self.assertEqual(len(sdists), 1)
            self.assert_sdist_document_contract(sdists[0])

    def test_sdist_wheel_and_sdist_rebuilt_wheel_have_identical_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            dist = root / "dist"
            rebuilt = root / "rebuilt"
            builder = root / "builder"
            runtime_environment = root / "runtime-venv"
            runtime = root / "runtime"
            dist.mkdir()
            rebuilt.mkdir()
            runtime.mkdir()
            shutil.copytree(
                ROOT,
                source,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".venv",
                    "__pycache__",
                    "build",
                    "dist",
                    "*.egg-info",
                ),
            )

            clean_environment = os.environ.copy()
            clean_environment.pop("PYTHONPATH", None)
            clean_environment["PYTHONNOUSERSITE"] = "1"
            venv.EnvBuilder(with_pip=True).create(builder)
            builder_python = builder / "bin" / "python"
            uv = shutil.which("uv")
            install_builder = (
                [
                    uv,
                    "pip",
                    "install",
                    "--offline",
                    "--python",
                    str(builder_python),
                    "build>=1.2",
                    "setuptools>=68",
                    "wheel",
                ]
                if uv is not None
                else [
                    str(builder_python),
                    "-m",
                    "pip",
                    "install",
                    "build>=1.2",
                    "setuptools>=68",
                    "wheel",
                ]
            )
            subprocess.run(
                install_builder,
                check=True,
                env=clean_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            subprocess.run(
                [
                    str(builder_python),
                    "-m",
                    "build",
                    "--sdist",
                    "--wheel",
                    "--outdir",
                    str(dist),
                    str(source),
                ],
                check=True,
                env=clean_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            wheels = tuple(dist.glob("openfundscore-*.whl"))
            sdists = tuple(dist.glob("openfundscore-*.tar.gz"))
            self.assertEqual(len(wheels), 1)
            self.assertEqual(len(sdists), 1)
            self.assert_wheel_contract(wheels[0])
            self.assert_sdist_document_contract(sdists[0])
            wheel_payloads = _wheel_resources(wheels[0])
            sdist_payloads = _sdist_resources(sdists[0])
            self.assertEqual(wheel_payloads, sdist_payloads)
            # __init__.py + index.json + all fifteen indexed logical resources.
            self.assertEqual(frozenset(wheel_payloads), _EXPECTED_RESOURCE_PAYLOADS)

            subprocess.run(
                [
                    str(builder_python),
                    "-m",
                    "pip",
                    "wheel",
                    str(sdists[0]),
                    "--no-deps",
                    "--wheel-dir",
                    str(rebuilt),
                ],
                check=True,
                env=clean_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            rebuilt_wheels = tuple(rebuilt.glob("openfundscore-*.whl"))
            self.assertEqual(len(rebuilt_wheels), 1)
            self.assert_wheel_contract(rebuilt_wheels[0])
            self.assertEqual(wheel_payloads, _wheel_resources(rebuilt_wheels[0]))

            venv.EnvBuilder(with_pip=True).create(runtime_environment)
            runtime_python = runtime_environment / "bin" / "python"
            subprocess.run(
                [
                    str(runtime_python),
                    "-m",
                    "pip",
                    "install",
                    "--force-reinstall",
                    "--no-deps",
                    str(rebuilt_wheels[0]),
                ],
                check=True,
                env=clean_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            shutil.rmtree(source)
            probe = subprocess.run(
                [
                    str(runtime_python),
                    "-c",
                    (
                        "from openfundscore.resources import list_resources,resolve_resource;"
                        "items=list_resources();"
                        "selectors={(i.key.resource_type.value,i.key.name,i.key.version)"
                        " for i in items};"
                        f"assert selectors=={_EXPECTED_RESOURCE_SELECTORS!r};"
                        "[resolve_resource(resource_type=i.key.resource_type,"
                        "name=i.key.name,version=i.key.version).load_json() for i in items];"
                        "print('sdist-wheel-ok')"
                    ),
                ],
                check=False,
                cwd=runtime,
                env=clean_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                probe.returncode,
                0,
                msg=f"stdout={probe.stdout}\nstderr={probe.stderr}",
            )
            self.assertEqual(probe.stdout.strip(), "sdist-wheel-ok")


if __name__ == "__main__":
    unittest.main()
