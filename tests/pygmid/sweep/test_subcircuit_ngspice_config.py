import shutil
from pathlib import Path

import pytest

from pygmid.sweep.config import NgspiceSky130Config, NgspiceGf180Config
from pygmid.sweep.simulator import NgspiceSimulator


CONFIG_SKY130 = Path('tests/pygmid/sweep/config_sky130.cfg').absolute()
CONFIG_GF180 = Path('tests/pygmid/sweep/config_gf180.cfg').absolute()

SKY130_PDK = Path.home() / '.ciel' / 'sky130B'
GF180_PDK = Path.home() / '.ciel' / 'gf180mcuD'


@pytest.fixture
def sky130_cfg(tmp_path, monkeypatch):
    cfg_path = tmp_path / 'config_sky130.cfg'
    cfg_path.write_text(CONFIG_SKY130.read_text())
    monkeypatch.chdir(tmp_path)
    return NgspiceSky130Config(cfg_path.name)


@pytest.fixture
def gf180_cfg(tmp_path, monkeypatch):
    cfg_path = tmp_path / 'config_gf180.cfg'
    cfg_path.write_text(CONFIG_GF180.read_text())
    monkeypatch.chdir(tmp_path)
    return NgspiceGf180Config(cfg_path.name)


def test_sky130_netlist_uses_x_prefix_not_flat_m(sky130_cfg):
    lines = Path(sky130_cfg.netlist_filename).read_text().splitlines()
    assert any(line.startswith('Xmn ') for line in lines)
    assert any(line.startswith('Xmp ') for line in lines)
    assert not any(line.startswith('Mn ') or line.startswith('Mp ') for line in lines)


def test_gf180_netlist_uses_x_prefix_not_flat_m(gf180_cfg):
    lines = Path(gf180_cfg.netlist_filename).read_text().splitlines()
    assert any(line.startswith('Xmn ') for line in lines)
    assert any(line.startswith('Xmp ') for line in lines)
    assert not any(line.startswith('Mn ') or line.startswith('Mp ') for line in lines)


def test_sky130_probes_use_modelname_derived_internal_name(sky130_cfg):
    netlist = Path(sky130_cfg.netlist_filename).read_text()
    assert '@m.xmn.msky130_fd_pr__nfet_01v8[id]' in netlist
    assert '@m.xmp.msky130_fd_pr__pfet_01v8[id]' in netlist


def test_gf180_probes_use_fixed_m0(gf180_cfg):
    netlist = Path(gf180_cfg.netlist_filename).read_text()
    assert '@m.xmn.m0[id]' in netlist
    assert '@m.xmp.m0[id]' in netlist


def test_sky130_length_is_bare_symbolic_expression(sky130_cfg):
    netlist = Path(sky130_cfg.netlist_filename).read_text()
    assert 'L={length}' in netlist
    # Never a resolved Python float -- the netlist is generated once, but
    # length is swept per-point via params.lib.
    assert 'L={length*1e-6}' not in netlist


def test_gf180_length_is_meters_symbolic_expression(gf180_cfg):
    netlist = Path(gf180_cfg.netlist_filename).read_text()
    assert 'L={length*1e-6}' in netlist


def test_gf180_extra_include_precedes_model_include(gf180_cfg):
    lines = Path(gf180_cfg.netlist_filename).read_text().splitlines()
    include_idx = next(i for i, l in enumerate(lines) if l.startswith('.include') and 'design.lib' in l)
    lib_idx = next(i for i, l in enumerate(lines) if l.startswith('.lib') and 'model.lib' in l)
    assert include_idx < lib_idx


def test_sky130_extra_include_absent_by_default(sky130_cfg):
    netlist = Path(sky130_cfg.netlist_filename).read_text()
    assert netlist.count('.include') == 0 or 'design.lib' not in netlist


def test_instance_tail_formula_matches_verified_proc_char_testbench(sky130_cfg):
    """ Regression test for the ad/as/pd/ps/nrd/nrs formula -- verified
    against real, currently-used proc_char testbenches
    (tb_ejf_sacomp.spice for sky130, tb_gf180mcu.spice for gf180mcuD),
    which both use this exact shape, differing only by the diffusion
    spacing constant (0.29 sky130, 0.18 gf180).
    """
    width, nf = 0.97, 1
    tail = sky130_cfg._instance_tail(width, nf)
    spacing = 0.29
    expected_ad = int((nf + 1) / 2) * width / nf * spacing
    expected_pd = 2 * int((nf + 1) / 2) * (width / nf + spacing)
    expected_nrd = spacing / width
    assert f'ad={expected_ad}' in tail
    assert f'pd={expected_pd}' in tail
    assert f'nrd={expected_nrd}' in tail
    # sa/sb/sd deliberately omitted -- both PDKs' subckts already default
    # them to 0, and hardcoding them here would conflict with a caller
    # overriding them via [MODEL] MN/MP.
    assert 'sa=' not in tail
    assert 'sb=' not in tail
    assert 'sd=' not in tail


def test_instance_tail_geom_values_are_unit_suffixed_for_gf180(gf180_cfg):
    width, nf = 0.97, 1
    tail = gf180_cfg._instance_tail(width, nf)
    assert f'W={width}u' in tail
    # nrd/nrs are dimensionless (spacing/width) -- never suffixed.
    spacing = 0.18
    expected_nrd = spacing / width
    assert f'nrd={expected_nrd} ' in tail
    assert f'nrd={expected_nrd}u' not in tail


def test_instance_tail_area_values_are_pico_suffixed_for_gf180(gf180_cfg):
    """ Regression test for a confirmed bug: ad/as are um^2-valued areas,
    not um-valued lengths, so they need a `p` (pico, 1e-12) suffix, not `u`
    (micro, 1e-6) -- `u` on ad/as inflated capbd/capbs from ~1fF to
    ~100-170pF for a W=1um device (off by (1e6)**2, i.e. um^2 vs m^2).
    """
    width, nf = 0.97, 1
    tail = gf180_cfg._instance_tail(width, nf)
    spacing = 0.18
    expected_ad = int((nf + 1) / 2) * width / nf * spacing
    expected_as = int((nf + 2) / 2) * width / nf * spacing
    assert f'ad={expected_ad}p' in tail
    assert f'as={expected_as}p' in tail
    assert f'ad={expected_ad}u' not in tail
    assert f'as={expected_as}u' not in tail


def test_instance_tail_geom_values_are_bare_for_sky130(sky130_cfg):
    width, nf = 0.97, 1
    tail = sky130_cfg._instance_tail(width, nf)
    assert f'W={width} ' in tail
    assert f'W={width}u' not in tail


def test_instance_tail_area_values_are_bare_for_sky130(sky130_cfg):
    """ sky130's ad/as stay bare (unlike gf180's `p` suffix) -- ngspice's
    `scale` option is dimension-aware for MOSFET instance params and
    squares the factor itself for area-type ones (AD/AS), so the same bare
    number that gives correct length under `scale=1.0u` also gives correct
    area, with no separate area suffix needed.
    """
    width, nf = 0.97, 1
    tail = sky130_cfg._instance_tail(width, nf)
    spacing = 0.29
    expected_ad = int((nf + 1) / 2) * width / nf * spacing
    assert f'ad={expected_ad} ' in tail
    assert f'ad={expected_ad}p' not in tail


@pytest.mark.skipif(
    shutil.which('ngspice') is None or not SKY130_PDK.exists(),
    reason="ngspice binary or ~/.ciel/sky130B PDK not found",
)
def test_sky130_dc_sweep_end_to_end(tmp_path, monkeypatch):
    """ Runs the generated sky130 netlist through a real ngspice binary
    against the real PDK. Skipped (not xfail) when unavailable -- this is a
    real regression check on development machines that have the PDK
    installed under ~/.ciel, not portable to CI.
    """
    text = CONFIG_SKY130.read_text()
    text = text.replace('file = model.lib\n', f'file = {SKY130_PDK}/libs.tech/combined/sky130.lib.spice\n')
    cfg_path = tmp_path / 'config_sky130.cfg'
    cfg_path.write_text(text)
    monkeypatch.chdir(tmp_path)

    cfg = NgspiceSky130Config(cfg_path.name)
    cfg._write_params(length=0.18, sb=0.0)
    sim = NgspiceSimulator()
    sim.directory = 'sweep_out'
    sim.run(cfg.netlist_filename)

    nmos, pmos = cfg._extract_sweep_params('sweep_out')
    n_vgs = len(cfg._config['SWEEP']['VGS'])
    n_vds = len(cfg._config['SWEEP']['VDS'])
    assert nmos['mn:id'].shape == (n_vgs, n_vds)
    assert pmos['mp:id'].shape == (n_vgs, n_vds)
    assert nmos['mn:id'].max() > 0
    assert pmos['mp:id'].max() > 0
    assert nmos['mn:vth'].mean() > 0
    assert pmos['mp:vth'].mean() > 0


@pytest.mark.skipif(
    shutil.which('ngspice') is None or not GF180_PDK.exists(),
    reason="ngspice binary or ~/.ciel/gf180mcuD PDK not found",
)
def test_gf180_dc_sweep_end_to_end(tmp_path, monkeypatch):
    text = CONFIG_GF180.read_text()
    text = text.replace('file = model.lib\n', f'file = {GF180_PDK}/libs.tech/ngspice/sm141064.ngspice\n')
    text = text.replace('extra_include = ["design.lib"]\n',
                         f'extra_include = ["{GF180_PDK}/libs.tech/ngspice/design.ngspice"]\n')
    cfg_path = tmp_path / 'config_gf180.cfg'
    cfg_path.write_text(text)
    monkeypatch.chdir(tmp_path)

    cfg = NgspiceGf180Config(cfg_path.name)
    cfg._write_params(length=0.28, sb=0.0)
    sim = NgspiceSimulator()
    sim.directory = 'sweep_out'
    sim.run(cfg.netlist_filename)

    nmos, pmos = cfg._extract_sweep_params('sweep_out')
    n_vgs = len(cfg._config['SWEEP']['VGS'])
    n_vds = len(cfg._config['SWEEP']['VDS'])
    assert nmos['mn:id'].shape == (n_vgs, n_vds)
    assert pmos['mp:id'].shape == (n_vgs, n_vds)
    assert nmos['mn:id'].max() > 0
    assert pmos['mp:id'].max() > 0
    assert nmos['mn:vth'].mean() > 0
    assert pmos['mp:vth'].mean() > 0
