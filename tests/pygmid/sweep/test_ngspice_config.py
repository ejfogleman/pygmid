import shutil
from pathlib import Path

import numpy as np
import pytest

from pygmid.sweep.config import NgspiceConfig
from pygmid.sweep.simulator import NgspiceSimulator


CONFIG_NGSPICE = Path('tests/pygmid/sweep/config_ngspice.cfg').absolute()
MODEL_FILE = Path('tests/pygmid/sweep/generic_bsim4.lib').absolute()


def _write_config(tmp_path, extra_model_lines=""):
    """ Copy the sample ngspice config (and its model file) into tmp_path,
    optionally injecting extra `[MODEL]` lines right after the header (e.g.
    a `libname = ...` key).
    """
    text = CONFIG_NGSPICE.read_text()
    text = text.replace("[MODEL]\n", f"[MODEL]\n{extra_model_lines}", 1)
    cfg_path = tmp_path / "config_ngspice.cfg"
    cfg_path.write_text(text)
    shutil.copy(MODEL_FILE, tmp_path / "generic_bsim4.lib")
    return cfg_path


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    cfg_path = _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    return NgspiceConfig(cfg_path.name)


def test_netlist_uses_plain_include_without_libname(cfg):
    lines = Path(cfg.netlist_filename).read_text().splitlines()
    assert any(line.startswith('.include') and 'generic_bsim4.lib' in line for line in lines)
    assert not any(line.startswith('.lib') for line in lines)


def test_netlist_uses_lib_when_libname_set(tmp_path, monkeypatch):
    cfg_path = _write_config(tmp_path, extra_model_lines="libname = tt\n")
    monkeypatch.chdir(tmp_path)
    ngcfg = NgspiceConfig(cfg_path.name)
    lines = Path(ngcfg.netlist_filename).read_text().splitlines()
    assert any(line.startswith('.lib') and 'generic_bsim4.lib tt' in line for line in lines)


def test_netlist_has_independent_real_polarity_bias(cfg):
    netlist = Path(cfg.netlist_filename).read_text()
    for src in ('Vgs_n', 'Vds_n', 'Vbs_n', 'Vgs_p', 'Vds_p', 'Vbs_p'):
        assert src in netlist
    assert 'wrdata mn.txt' in netlist
    assert 'wrdata mp.txt' in netlist
    # No `reset` needed between the two DC/save/wrdata sequences.
    assert 'reset' not in netlist


def test_generate_outvars_row_order_matches_dc_params(cfg):
    n, p, n_noise, p_noise = cfg._generate_outvars()
    assert [row[0].split(':', 1)[1] for row in n] == NgspiceConfig._DC_PARAMS
    assert [row[0].split(':', 1)[1] for row in p] == NgspiceConfig._DC_PARAMS
    assert len(n) == len(p)


def test_generate_outvars_pmos_id_vth_not_negated(cfg):
    """ Regression test for the ngspice-specific sign convention: ngspice
    reports PMOS id/vth positive (empirically verified), unlike
    SpectreConfig.p's -1 coefficients. Getting this backwards would
    silently double-negate PMOS ID/VT in generated lookup tables.
    """
    n, p, _, _ = cfg._generate_outvars()
    outvars = cfg._config['outvars']
    id_idx = outvars.index('ID')
    vt_idx = outvars.index('VT')

    n_id = next(row for row in n if row[0] == 'mn:id')
    n_vth = next(row for row in n if row[0] == 'mn:vth')
    p_id = next(row for row in p if row[0] == 'mp:id')
    p_vth = next(row for row in p if row[0] == 'mp:vth')

    assert n_id[2][id_idx] == 1
    assert n_vth[2][vt_idx] == 1
    assert p_id[2][id_idx] == 1
    assert p_vth[2][vt_idx] == 1


def test_generate_outvars_igd_igs_left_zero(cfg):
    n, p, _, _ = cfg._generate_outvars()
    outvars = cfg._config['outvars']
    igd_idx = outvars.index('IGD')
    igs_idx = outvars.index('IGS')
    for row in n + p:
        assert row[2][igd_idx] == 0
        assert row[2][igs_idx] == 0


def test_extract_sweep_params_dc_parses_wrdata_columns(cfg, tmp_path):
    n_vgs = len(cfg._config['SWEEP']['VGS'])
    n_vds = len(cfg._config['SWEEP']['VDS'])
    n_points = n_vgs * n_vds
    n_params = len(NgspiceConfig._DC_PARAMS)

    # Synthetic `wrdata`-format file: interleaved (scale, value) column
    # pairs, VGS varying fastest/inner and VDS slowest/outer -- matches
    # ngspice's actual two-source `.dc Vgs ... Vds ...` row order (verified
    # against a real ngspice run during development).
    data = np.zeros((n_points, 2 * n_params))
    for k in range(n_params):
        data[:, 2 * k] = 0.0  # scale column, discarded by the parser
        data[:, 2 * k + 1] = 100 * k + np.arange(n_points)

    out_dir = tmp_path / "sim_out"
    out_dir.mkdir()
    np.savetxt(out_dir / "mn.txt", data)
    np.savetxt(out_dir / "mp.txt", data)

    nmos, pmos = cfg._extract_sweep_params(str(out_dir))

    for k, param in enumerate(NgspiceConfig._DC_PARAMS):
        expected = np.zeros((n_vgs, n_vds))
        for r in range(n_points):
            expected[r % n_vgs, r // n_vgs] = 100 * k + r

        assert nmos[f'mn:{param}'].shape == (n_vgs, n_vds)
        assert np.array_equal(nmos[f'mn:{param}'], expected)
        assert np.array_equal(pmos[f'mp:{param}'], expected)


def test_extract_sweep_params_noise_returns_zero_stub(cfg):
    n_vgs = len(cfg._config['SWEEP']['VGS'])
    n_vds = len(cfg._config['SWEEP']['VDS'])
    nn, pn = cfg._extract_sweep_params('unused', sweep_type="NOISE")
    assert nn['mn:noise_stub'].shape == (n_vgs, n_vds)
    assert pn['mp:noise_stub'].shape == (n_vgs, n_vds)
    assert np.all(nn['mn:noise_stub'] == 0)
    assert np.all(pn['mp:noise_stub'] == 0)


def test_extract_sweep_params_unknown_type_raises(cfg):
    with pytest.raises(ValueError, match="Unknown sweep type"):
        cfg._extract_sweep_params('unused', sweep_type="BOGUS")


@pytest.mark.skipif(shutil.which('ngspice') is None, reason="ngspice binary not found on PATH")
def test_ngspice_dc_sweep_end_to_end(cfg):
    """ Runs the generated netlist through a real ngspice binary. Skipped
    (not xfail) when ngspice isn't installed, e.g. in CI -- this is a real
    regression check for environments (including development machines)
    that do have it.
    """
    cfg._write_params(length=1, sb=0.0)
    sim = NgspiceSimulator()
    sim.directory = 'sweep_out'
    result = sim.run(cfg.netlist_filename)
    assert result == 'sweep_out'

    nmos, pmos = cfg._extract_sweep_params('sweep_out')

    n_vgs = len(cfg._config['SWEEP']['VGS'])
    n_vds = len(cfg._config['SWEEP']['VDS'])
    assert nmos['mn:id'].shape == (n_vgs, n_vds)
    assert pmos['mp:id'].shape == (n_vgs, n_vds)

    # The key ngspice-specific regression: PMOS id/vth come back positive,
    # same as NMOS (unlike Spectre's mp:ids/mp:vth, which are negative).
    assert nmos['mn:id'].min() >= 0
    assert pmos['mp:id'].min() >= 0
    assert nmos['mn:vth'].mean() > 0
    assert pmos['mp:vth'].mean() > 0
