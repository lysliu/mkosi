# SPDX-License-Identifier: LGPL-2.1+

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

from mkosi.config import Args, Config
from mkosi.tree import make_tree
from mkosi.types import PathString
from mkosi.util import flatten, umask


class Context:
    """State related properties."""

    def __init__(
        self,
        args: Args,
        config: Config,
        *,
        workspace: Path,
        resources: Path,
        package_cache_dir: Optional[Path] = None,
    ) -> None:
        self.args = args
        self.config = config
        self.workspace = workspace
        self.resources = resources
        self.package_cache_dir = package_cache_dir or (self.root / "var")

        with umask(~0o755):
            # Using a btrfs subvolume as the upperdir in an overlayfs results in EXDEV so make sure we create
            # the root directory as a regular directory if the Overlay= option is enabled.
            if config.overlay:
                self.root.mkdir()
            else:
                make_tree(
                    self.root,
                    use_subvolumes=self.config.use_subvolumes,
                    tools=config.tools(),
                    sandbox=config.sandbox,
                )

        self.staging.mkdir()
        self.pkgmngr.mkdir()
        self.packages.mkdir()
        self.install_dir.mkdir(exist_ok=True)

    @property
    def root(self) -> Path:
        return self.workspace / "root"

    @property
    def staging(self) -> Path:
        return self.workspace / "staging"

    @property
    def pkgmngr(self) -> Path:
        return self.workspace / "pkgmngr"

    @property
    def packages(self) -> Path:
        return self.workspace / "packages"

    @property
    def install_dir(self) -> Path:
        return self.workspace / "dest"

    def sandbox(
        self,
        *,
        network: bool = False,
        devices: bool = False,
        scripts: Optional[Path] = None,
        options: Sequence[PathString] = (),
    ) -> list[PathString]:
        return self.config.sandbox(
            network=network,
            devices=devices,
            scripts=scripts,
            options=[
                "--uid", "0",
                "--gid", "0",
                "--cap-add", "ALL",
                # These mounts are writable so bubblewrap can create extra directories or symlinks inside of it as
                # needed. This isn't a problem as the package manager directory is created by mkosi and thrown away
                # when the build finishes.
                *flatten(
                    ["--bind", os.fspath(self.pkgmngr / "etc" / p.name), f"/etc/{p.name}"]
                    for p in (self.pkgmngr / "etc").iterdir()
                ),
                *options,
                "--bind", self.pkgmngr / "var/log", "/var/log",
                *(["--ro-bind", os.fspath(p), os.fspath(p)] if (p := self.pkgmngr / "usr").exists() else []),
            ],
        ) + (
            [
                "sh",
                "-c",
                f"mount -t overlay -o lowerdir={self.pkgmngr / 'usr'}:/usr overlayfs /usr && exec $0 \"$@\"",
            ] if (self.pkgmngr / "usr").exists() else []
        )

    def want_local_repo(self) -> bool:
        return any(self.packages.iterdir())
