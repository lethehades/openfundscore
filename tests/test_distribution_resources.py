from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
_RESOURCE_PREFIX = "openfundscore/_resources/"


def _wheel_resources(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {
            name.removeprefix(_RESOURCE_PREFIX): archive.read(name)
            for name in archive.namelist()
            if name.startswith(_RESOURCE_PREFIX)
        }


def _sdist_resources(path: Path) -> dict[str, bytes]:
    with tarfile.open(path, "r:gz") as archive:
        resources: dict[str, bytes] = {}
        for member in archive.getmembers():
            marker = "/src/" + _RESOURCE_PREFIX
            if marker not in member.name or not member.isfile():
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            resources[member.name.split(marker, 1)[1]] = extracted.read()
        return resources


class DistributionResourceTests(unittest.TestCase):
    def test_sdist_wheel_and_sdist_rebuilt_wheel_have_identical_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            dist = root / "dist"
            rebuilt = root / "rebuilt"
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
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "build",
                    "--no-isolation",
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
            wheel_payloads = _wheel_resources(wheels[0])
            sdist_payloads = _sdist_resources(sdists[0])
            self.assertEqual(wheel_payloads, sdist_payloads)
            self.assertEqual(len(wheel_payloads), 11)

            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    str(sdists[0]),
                    "--no-deps",
                    "--no-build-isolation",
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
            self.assertEqual(wheel_payloads, _wheel_resources(rebuilt_wheels[0]))

            venv.EnvBuilder(with_pip=True, system_site_packages=True).create(
                runtime_environment
            )
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
                        "items=list_resources();assert len(items)==9;"
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
