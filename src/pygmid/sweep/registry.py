""" Simulator backend registry.

Maps a simulator name (as given by the `[MODEL] simulator` config key) to
the `(SweepConfig subclass, Simulator instance factory)` pair used to run a
sweep with that backend.

Adding a new backend is a matter of implementing a `SweepConfig` subclass
and a `Simulator`-compatible class, then adding one entry here -- no
changes to `Sweep` itself are required.
"""

from .config import SpectreConfig, NgspiceConfig, NgspiceSky130Config, NgspiceGf180Config
from .simulator import SpectreSimulator, NgspiceSimulator

# Command-line arguments passed to `spectre` on every invocation. The last
# element is a placeholder for the per-simulation output directory, which
# `SpectreSimulator.directory` overwrites before each run.
SPECTRE_ARGS = ['+escchars',
        '=log',
        './sweep/psf/spectre.out',
        '-format',
        'psfascii',
        '-raw',
        './sweep/psf']

# Each entry maps a simulator name to a `(ConfigClass, simulator_factory)`
# pair. `simulator_factory` is a zero-argument callable returning a fresh
# `Simulator`-compatible instance (a plain class reference also works if its
# constructor takes no required arguments).
SIMULATOR_REGISTRY = {
    'spectre': (SpectreConfig, lambda: SpectreSimulator(*SPECTRE_ARGS)),
    'ngspice': (NgspiceConfig, NgspiceSimulator),
    'ngspice_sky130':  (NgspiceSky130Config, NgspiceSimulator),
    'ngspice_gf180':   (NgspiceGf180Config, NgspiceSimulator),
}


def get_simulator_backend(name: str):
    """ Look up the `(ConfigClass, simulator_factory)` pair registered for
    `name` (case-insensitive).

    Raises `ValueError` if no backend is registered under that name.
    """
    key = name.strip().lower()
    try:
        return SIMULATOR_REGISTRY[key]
    except KeyError:
        available = ', '.join(sorted(SIMULATOR_REGISTRY.keys()))
        raise ValueError(
            f"Unknown simulator backend '{name}'. Available backends: {available}"
        )
