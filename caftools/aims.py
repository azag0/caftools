# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from .convert import p2f
from pathlib import Path
import shutil

from typing import Dict, Any, List, Tuple, Callable  # noqa
from mypy_extensions import KwArg  # noqa
from . import geomlib2  # noqa


class AimsNotFound(Exception):
    pass


class AimsTask:
    default_features = ['speciedir', 'tags', 'command', 'basis', 'geom', 'core']

    def __init__(self, features: List[str] = None) -> None:
        self.basis_defs: Dict[Tuple[Path, str], str] = {}
        self.speciedirs: Dict[Tuple[str, str], Path] = {}
        self.features: List[Callable[[KwArg(Any)], Dict[str, Any]]] = [
            getattr(self, feat) for feat in features or self.default_features
        ]

    def __call__(self, **kwargs: Any) -> Dict[str, Any]:
        for feature in self.features:
            kwargs = feature(**kwargs)
        return kwargs

    def speciedir(self, *, aims: str, basis: str, **kwargs: Any) -> Dict[str, Any]:
        basis_key = aims, basis
        if basis_key in self.speciedirs:
            speciedir = self.speciedirs[basis_key]
        else:
            pathname = shutil.which(aims)
            if not pathname:
                raise AimsNotFound(aims)
            path = Path(pathname)
            speciedir = path.parents[1]/'aimsfiles/species_defaults'/basis
            self.speciedirs[basis_key] = speciedir
        return dict(**kwargs, aims=aims, speciedir=speciedir)

    def tags(self, tags: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
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
        control = '\n'.join(lines)
        return dict(**kwargs, control=control)

    def command(self, aims: str, check: bool = True,
                **kwargs: Any) -> Dict[str, Any]:
        command = f'AIMS={aims} run_aims'
        if check:
            command += ' && grep "Have a nice day" run.out >/dev/null'
        return dict(**kwargs, command=command)

    def basis(self, *, geom: geomlib2.Molecule, speciedir: Path,
              **kwargs: Any) -> Dict[str, Any]:
        species = set([(a.number, a.specie) for a in geom.centers])
        basis = []
        for number, specie in sorted(species):
            if (speciedir, specie) not in self.basis_defs:
                basis_def = (speciedir/f'{number:02d}_{specie}_default').read_text()
                self.basis_defs[speciedir, specie] = basis_def
            else:
                basis_def = self.basis_defs[speciedir, specie]
            basis.append(basis_def)
        return dict(**kwargs, geom=geom, basis=basis)

    def geom(self, *, geom: geomlib2.Molecule, **kwargs: Any) -> Dict[str, Any]:
        return dict(**kwargs, geometry=geom.dumps('aims'))

    def core(self, *, control: str, basis: List[str], geometry: str, inputs: List,
             **kwargs: Any) -> Dict[str, Any]:
        control = '\n\n'.join([control, *basis])
        return dict(**kwargs, inputs=[
            ('control.in', control),
            ('geometry.in', geometry),
        ])


def _kwid(**kw: Any) -> Dict[str, Any]:
    return kw


class AimsWriter:
    rules: Dict[str, Callable] = {
        'ROOT': lambda species: species,
        'species': lambda label, basis, angular_grids, valence, ion_occ, **kw: [
            ('species', label), kw, angular_grids, valence, ion_occ, basis
        ],
        'cut_pot': lambda onset, width, scale: (onset, width, scale),
        'radial_base': lambda number, radius: (number, radius),
        'angular_grids': lambda shells: [('angular_grids', 'specified'), shells],
        'shells': lambda points, radius=None: (
            ('division', radius, points) if radius
            else ('outer_grid', points)
        ),
        'valence': lambda n, l, occupation: ('valence', n, l, occupation),
        'ion_occ': lambda n, l, occupation: ('ion_occ', n, l, occupation),
        'basis': lambda type, n, l, radius=None, z_eff=None: (
            (type, n, l, radius) if type == 'ionic'
            else (type, n, l, z_eff)
        ),
    }

    def __init__(self, rules: Dict[str, Callable] = None) -> None:
        if rules:
            self.rules = rules

    def stringify(self, value: Any) -> str:
        if isinstance(value, bool):
            return f'.{str(value).lower()}.'
        if isinstance(value, tuple):
            return ' '.join(self.stringify(x) for x in value)
        if isinstance(value, list):
            return '\n'.join(self.stringify(x) for x in value)
        if isinstance(value, dict):
            return '\n'.join(
                f'{k} {self.stringify(v)}' if v is not None else k
                for k, v in sorted(value.items())
            )
        return str(value)

    def _transform_value(self, val: Any, rule: str) -> Any:
        if isinstance(val, list):
            return [self._transform_value(x, rule) for x in val]
        if isinstance(val, dict):
            return self.rules.get(rule, _kwid)(**self._transform_node(val))
        return val

    def _transform_node(self, node: Any) -> Any:
        if isinstance(node, dict):
            return {k: self._transform_value(v, k) for k, v in node.items()}
        return node

    def transform(self, node: Any, root: str = 'ROOT') -> Any:
        return self._transform_node({root: node})[root]

    def write(self, node: Any, root: str = 'ROOT') -> str:
        value = self.transform(node, root=root)
        return self.stringify(value)
