import shutil
from pathlib import Path

import pytest

from pygmid.sweep import SIMULATOR_REGISTRY, get_simulator_backend
from pygmid.sweep.config import SpectreConfig, NgspiceConfig
from pygmid.sweep.simulator import SpectreSimulator, NgspiceSimulator
from pygmid.sweep.sweep import Sweep


SAMPLE_CONFIG = Path('tests/pygmid/sweep/sample_config.cfg').absolute()
CONFIG_NGSPICE = Path('tests/pygmid/sweep/config_ngspice.cfg').absolute()
NGSPICE_MODEL_FILE = Path('tests/pygmid/sweep/generic_bsim4.lib').absolute()


def _write_config(tmp_path, extra_model_lines=""):
    """ Copy the sample config (which has no `simulator` key of its own),
    optionally injecting extra `[MODEL]` lines (e.g. a `simulator = ...`
    key) right after the `[MODEL]` header.
    """
    text = SAMPLE_CONFIG.read_text()
    text = text.replace("[MODEL]\n", f"[MODEL]\n{extra_model_lines}", 1)
    cfg_path = tmp_path / "config.cfg"
    cfg_path.write_text(text)
    return cfg_path


def _write_ngspice_config(tmp_path):
    """ Copy the sample ngspice config (which already has `simulator =
    ngspice`) and its model file into tmp_path.
    """
    cfg_path = tmp_path / "config_ngspice.cfg"
    cfg_path.write_text(CONFIG_NGSPICE.read_text())
    shutil.copy(NGSPICE_MODEL_FILE, tmp_path / "generic_bsim4.lib")
    return cfg_path


def test_registry_contains_spectre_backend():
    assert 'spectre' in SIMULATOR_REGISTRY
    config_cls, simulator_factory = SIMULATOR_REGISTRY['spectre']
    assert config_cls is SpectreConfig
    assert isinstance(simulator_factory(), SpectreSimulator)


def test_get_simulator_backend_is_case_insensitive():
    config_cls, _ = get_simulator_backend('SPECTRE')
    assert config_cls is SpectreConfig
    config_cls, _ = get_simulator_backend(' Spectre ')
    assert config_cls is SpectreConfig


def test_get_simulator_backend_unknown_raises():
    with pytest.raises(ValueError, match="Unknown simulator backend"):
        get_simulator_backend('not-a-real-simulator')


def test_sweep_defaults_to_spectre_when_simulator_key_absent(tmp_path, monkeypatch):
    cfg_path = _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    swp = Sweep(str(cfg_path))
    assert isinstance(swp._config, SpectreConfig)
    assert isinstance(swp._simulator, SpectreSimulator)


def test_sweep_honors_explicit_simulator_key(tmp_path, monkeypatch):
    cfg_path = _write_config(tmp_path, extra_model_lines="simulator = spectre\n")
    monkeypatch.chdir(tmp_path)
    swp = Sweep(str(cfg_path))
    assert isinstance(swp._config, SpectreConfig)
    assert isinstance(swp._simulator, SpectreSimulator)


def test_sweep_raises_on_unknown_simulator_key(tmp_path, monkeypatch):
    cfg_path = _write_config(tmp_path, extra_model_lines="simulator = bogus\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="Unknown simulator backend"):
        Sweep(str(cfg_path))


def test_registry_contains_ngspice_backend():
    assert 'ngspice' in SIMULATOR_REGISTRY
    config_cls, simulator_factory = SIMULATOR_REGISTRY['ngspice']
    assert config_cls is NgspiceConfig
    assert isinstance(simulator_factory(), NgspiceSimulator)


def test_sweep_honors_ngspice_simulator_key(tmp_path, monkeypatch):
    cfg_path = _write_ngspice_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    swp = Sweep(str(cfg_path))
    assert isinstance(swp._config, NgspiceConfig)
    assert isinstance(swp._simulator, NgspiceSimulator)
