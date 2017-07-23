# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from .convert import p2f
from ..Configure import Task
from ..Logging import info, report
from pathlib import Path
import shutil

from typing import Callable, Dict, Tuple, Any, List
from . import geomlib2  # noqa
from ..Configure import Contents, Context

_reported: Dict[str, Tuple[Callable[[str], None], str]] = {}


@report
def reporter() -> None:
    for printer, msg in _reported.values():
        printer(msg)


species_db: Dict[Tuple[Path, str], str] = {}
aims_paths: Dict[str, Path] = {}


class AimsNotFound(Exception):
    pass


def get_aims_path(aims: str) -> Path:
    if aims in aims_paths:
        return aims_paths[aims]
    aims_full = shutil.which(aims)
    if not aims_full:
        raise AimsNotFound(aims)
    path = Path(aims_full).resolve()
    aims_paths[aims] = path
    return path


def delink_aims(aims: str) -> str:
    return get_aims_path(aims).name


class AimsTask(Task):
    def __init__(
            self, *,
            aims: str,
            basis: str,
            geom: geomlib2.Molecule,
            tags: Dict[str, Any],
            check: bool = True,
            ctx: Context,
            **kwargs: Any
    ) -> None:
        command, aims_path = self.get_aims(aims=aims, check=check, **kwargs)
        lines = self.get_base_control(tags=tags, **kwargs)
        basis_root = aims_path.parents[1]/'aimsfiles/species_defaults'/basis
        for basis_def in self.get_basis(root=basis_root, geom=geom, **kwargs):
            lines.extend(['', basis_def])
        inputs = [
            ('geometry.in', Contents(geom.dumps('aims'))),
            ('control.in', Contents('\n'.join(lines)))
        ]
        super().__init__(command=command, inputs=inputs, ctx=ctx)

    def get_aims(self, *, aims: str, check: bool, **kwargs: Any) -> Tuple[str, Path]:
        aims_path = get_aims_path(aims)
        command = f'AIMS={aims} run_aims'
        if check:
            command += ' && grep "Have a nice day" run.out >/dev/null'
        if aims not in _reported:
            _reported[aims] = (info, f'{aims} is {aims_path}')
        return command, aims_path

    def get_base_control(self, *, tags: Dict[str, Any], **kwargs: Any) -> List[str]:
        lines = []
        for tag, value in tags.items():
            if value is None:
                continue
            if value is ():
                lines.append(tag)
            elif isinstance(value, list):
                lines.extend(f'{tag}  {p2f(v)}' for v in value)
            else:
                if value == 'xc' and value.startswith('libxc'):
                    lines.append('override_warning_libxc')
                lines.append(f'{tag}  {p2f(value)}')
        return lines

    def get_basis(self, *, root: Path, geom: geomlib2.Molecule, **kwargs: Any) -> List[str]:
        species = set([(a.number, a.specie) for a in geom.centers])
        basis_defs = []
        for number, specie in sorted(species):
            if (root, specie) not in species_db:
                with (root/f'{number:02d}_{specie}_default').open() as f:
                    basis_def = f.read()
                species_db[root, specie] = basis_def
            else:
                basis_def = species_db[root, specie]
            basis_defs.append(basis_def)
        return basis_defs
