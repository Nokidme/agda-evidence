#!/usr/bin/env python3
"""Install each built alpha distribution in a fresh, external environment.

Wheel installation uses no index or runtime dependencies. Source installation
may fetch declared build tools; this is not an offline-replay test. The supplied
smoke script must test the installed package, not inject repository source paths.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import venv
import zipfile
from email.parser import Parser


def run(argv: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print("+", " ".join(argv), flush=True)
    subprocess.run(argv, cwd=cwd, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--smoke-script", type=Path, required=True)
    parser.add_argument("--agda-bin", help="optional native POSIX compiler check")
    args = parser.parse_args()
    directory = args.dist_dir.resolve(strict=True)
    script = args.smoke_script.resolve(strict=True)
    wheels = sorted(directory.glob("*.whl"))
    sources = sorted(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        parser.error("dist-dir must contain exactly one wheel and one source archive")
    with zipfile.ZipFile(wheels[0]) as archive:
        names = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            parser.error("wheel must have exactly one METADATA file")
        metadata = Parser().parsestr(archive.read(names[0]).decode("utf-8"))
        if metadata.get_all("Requires-Dist"):
            parser.error("reference package unexpectedly declares runtime dependencies")
    environment = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME"):
        environment.pop(key, None)
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    for artifact in (wheels[0], sources[0]):
        with tempfile.TemporaryDirectory(prefix="agda-package-install-") as temporary:
            root = Path(temporary)
            destination = root / "venv"
            venv.EnvBuilder(with_pip=True).create(destination)
            python = destination / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            working = root / "consumer"
            working.mkdir()
            install = [str(python), "-I", "-m", "pip", "install", "--no-deps"]
            if artifact.suffix == ".whl":
                install.append("--no-index")
            run([*install, str(artifact)], cwd=working, env=environment)
            run([str(python), "-I", "-m", "pip", "check"], cwd=working, env=environment)
            command = [str(python), "-I", str(script)]
            if args.agda_bin:
                command.extend(["--agda-bin", args.agda_bin])
            run(command, cwd=working, env=environment)
            print(f"PASS external install: {artifact.name}", flush=True)


if __name__ == "__main__":
    main()
