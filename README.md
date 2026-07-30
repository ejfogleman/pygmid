![Tests](https://github.com/dreoilin/pygmid/actions/workflows/run-tests.yml/badge.svg?branch=main)
![PyPI - Downloads](https://img.shields.io/pypi/dm/pygmid)
[![DOI](https://zenodo.org/badge/510693980.svg)](https://zenodo.org/badge/latestdoi/510693980)

<p align="center">
  <a>
    <img src="https://github.com/dreoilin/pygmid/blob/main/docs/img/icon.png?raw=true" width="80">
  </a>

  <h3 align="center">pygmid</h3>

  <p align="center">
    A python3 implementation of the gm/ID starter kit
    <br>
    <a href="https://www.github.com/dreoilin/pygmid/issues/new?template=bug.md">Report bug</a>
    ·
    <a href="https://www.github.com/dreoilin/pygmid/issues/new?template=feature.md&labels=feature">Request feature</a>
  </p>
</p>

## Table of contents

- [About](#about)
- [Installation](#installation)
- [Usage](#usage)
- [Citation](#citation)
- [Authors](#authors)

## About

pygmid is a Python 3 version of the gm/ID starter kit by Prof. Boris Murmann 
of Stanford University. The package also offers some scripts from the Paul Jesper's book.

If you find this package useful for your research, please consider citing it.

The original MATLAB gm/ID starter kit can be found [here](https://github.com/bmurmann/Book-on-gm-ID-design/tree/main/starter_kit)

## Installation

To install pygmid from source, download from Github and run pip:

`pip install .`

 in the root directory.

 pygmid can also be installed from PyPI:

`pip install pygmid`

## Usage

### Scripting with the Lookup Class
A gm/ID lookup object can be generated with the `Lookup` class. The lookup object requires lookup data for initialisation. Both `.mat` files generated using MATLAB or `.pkl` files generated using pygmid's own characterisation script are supported.

You can create a lookup object as follows:

```python
from pygmid import Lookup as lk

NCH = lk('180nch.mat')
```
### Access MOS Data
The `Lookup` class allows for pseudo array access of the MOS matrix data. You can access data as follows:

```python
# get VGS data as array from NCH
VGS_array = NCH['VGS']
```

Data is returned as a deep copy of the array contained in the `Lookup` object.

### Lookup functionality 

Lookup of interpolated data occurs as follows:

```python
VDSs = NCH['VDS'] 
VGSs = np.arange(0.4, 0.6, 0.05)
# Plot ID versus VDS
ID = NCH.look_up('ID', vds=VDSs, vgs=VGSs)
# alias function lookup can also be used
ID = NCH.lookup('ID', vds=VDSs, vgs=VGSs)
# check bias
VGS = NCH.look_upVGS(GM_ID = 10, VDS = 0.6, VSB = 0.1, L = 0.18)
print(f'VGS is: {VGS}')

plt.plot(VDSs, np.transpose(ID))
```

Modes 1 (Simple parameter lookup), mode 2 (arbitrary ratio lookup) and mode 3 (cross lookup of ratios) are implemented. The companion lookupVGS function is also included.

### Technology Extraction Functions

The EKV extraction function can be used as follows:

```python
from pygmid import EKV_param_extraction, XTRACT

(VDS, n, VT, JS, d1n, d1VT, d1logJS, d2n, d2VT, d2logJS)\
        = EKV_param_extraction(NCH, 1, L = 0.18, VDS = 0.6, VSB = 0.0)

```

Sample usage of this and other utility functions can be found in `debug_utility.py` .

### Examples

Usage of lookup scripts are given in `debug_lookup.py` and `debug_lookupVGS.py`.

Sample outputs for the 180nm generic pdk used in the Murmann starter pack are given below:

![image](https://github.com/dreoilin/pygmid/blob/main/docs/img/IDvVDS.png?raw=true)

![image](https://github.com/dreoilin/pygmid/blob/main/docs/img/vtvsL.png?raw=true)

![image](https://github.com/dreoilin/pygmid/blob/main/docs/img/gm_gds.png?raw=true)

![image](https://github.com/dreoilin/pygmid/blob/main/docs/img/ft.png?raw=true)

![image](https://github.com/dreoilin/pygmid/blob/main/docs/img/idwVDS.png?raw=true)

![image](https://github.com/dreoilin/pygmid/blob/main/docs/img/IDWvsgmID.png?raw=true)

The generic PDK data is hosted <a href="https://github.com/bmurmann/Book-on-gm-ID-design">here</a>.

### Sweeping a Technology

`pygmid` also features a CLI which drives a SPICE simulator across a grid of `(L, VSB, VGS, VDS)`
points to build the characterization tables consumed by `Lookup`. Two simulator backends are
currently supported: **Spectre** (default) and **ngspice**.

Run a sweep with:

```bash
python -m pygmid --mode sweep --config config.cfg
```

This writes two pickle files, `<SAVEFILEN>.pkl` and `<SAVEFILEP>.pkl`, which can be loaded directly
with `Lookup`:

```python
from pygmid import Lookup as lk

NCH = lk('90n1rvt.pkl')
```

Pass `--skip-run` to validate/parse a config without invoking the simulator (useful for testing a
config file).

#### Config file format

The config file is INI-style with two sections, `[MODEL]` and `[SWEEP]`. Keys are case-insensitive.

`[MODEL]`:

| Key | Description |
| --- | --- |
| `simulator` | Which backend to use: `spectre` (default if omitted) or `ngspice`. |
| `file` | Path to the model file. For Spectre this may include a `section=` suffix (e.g. `"path/to/models.scs" section=NN`). For ngspice, a plain path; pair with `libname` below if the file is wrapped in a `.lib ... .endl` block. |
| `libname` | *(ngspice only, optional)* Library name to pass to `.lib <file> <libname>`. Omit for model files with no `.lib`/`.endl` wrapper — a plain `.include` is used instead. |
| `info` | Free-text description, stored as metadata in the output table. |
| `corner` | Process corner label, stored as metadata. |
| `temp` | Temperature in Kelvin. |
| `modeln` / `modelp` | NMOS/PMOS model names to instantiate in the generated netlist. |
| `savefilen` / `savefilep` | Base filename (no extension) for the NMOS/PMOS output `.pkl` files. |
| `paramfile` | Filename for the per-simulation-point parameter file (length, body bias). Defaults to `params.scs` (Spectre) or `params.lib` (ngspice). |
| `mn` / `mp` | JSON list of extra per-device instance parameter lines appended to the NMOS/PMOS device statement (e.g. layout-dependent parasitics). Use `[]` if not needed — see the indentation note below. |

`[SWEEP]`:

| Key | Description |
| --- | --- |
| `VGS` / `VDS` / `VSB` | A `(start, step, stop)` tuple, or a list of such tuples for piecewise ranges. |
| `LENGTH` | A list of `(start, step, stop)` tuples — the channel lengths to sweep, in µm. |
| `WIDTH` | Total device width, in µm. |
| `NFING` | Number of fingers. |

A minimal ngspice example (see `tests/pygmid/sweep/config_ngspice.cfg` for the full sample used in
tests):

```ini
[MODEL]
simulator = ngspice
file = generic_bsim4.lib
info = Generic BSIM4
corner = TT
temp = 300
modeln = generic_nmos
modelp = generic_pmos
savefilen = ngspice_test_n
savefilep = ngspice_test_p
paramfile = params.lib
mn = []
mp = []

[SWEEP]
VGS = (0,0.6,1.8)
VDS = (0,0.9,1.8)
VSB = (0,0.5,0.5)
LENGTH = [(1,0.5,1)]
WIDTH = 10
NFING = 1
```

`mn`/`mp` is a plain JSON list of strings, each one an extra instance parameter appended to the
device statement (`key=value`, or an expression). If the list spans multiple lines, make sure each
continuation line is indented (configparser treats an indented line as a continuation of the
previous value — an unindented one is parsed as a new, duplicate key and raises
`DuplicateOptionError`), and that the list isn't left with a trailing comma, e.g.:

```ini
mn = ["l=L w=Wtot m=1",
    "ad=100"]
```

A trailing `\` inside a string (as in the Spectre sample config) is only needed if that particular
line is itself a Spectre netlist continuation — it's not part of the `mn`/`mp` syntax itself.

#### Adding a simulator backend

Backends are registered in `pygmid.sweep.SIMULATOR_REGISTRY`, keyed by the `simulator` config value.
Adding a new one means implementing a `SweepConfig` subclass (netlist generation, output-variable
mapping, and output parsing) and a class satisfying the `Simulator` protocol (a `directory` property
and a `run(filename)` method), then registering the pair — no changes to the sweep driver itself are
required.

## Citation

If you find this package useful in your research, please consider citing the following papers:

1. **M. Srivastava\***, **C. O’Donnell\***, B. Griffin, P. Cantillon-Murphy, and D. O’Hare  
   (*\*joint first authors*),  
   *“Efficient Bio-Sensing Amplifier Design: A Python-Based gm/ID Design Methodology,”*  
   **Proceedings of the IEEE Biomedical Circuits and Systems Conference (BioCAS)**, 2024.  
   DOI: [10.1109/BioCAS61083.2024.10798363](https://doi.org/10.1109/BioCAS61083.2024.10798363)

2. **T. Cortez**, **C. O’Donnell**, and **D. O’Hare**,  
   *“Low Power ADC Buffer: A Python-Based gm/ID Design Methodology,”*  
   **Proceedings of the 32nd IEEE International Conference on Electronics, Circuits and Systems (ICECS)**,  
   Marrakech, Morocco, 2025, pp. 1–4.  
   DOI: [10.1109/ICECS66544.2025.11270766](https://doi.org/10.1109/ICECS66544.2025.11270766)

## Authors

- Cian O'Donnell : cian.odonnell@mcci.ie
- Tiarnach Ó Riada : tiarnach.oriada@tyndall.ie
- Neil Stuart
- Danylo Galach

## Contributors

- José Rui Custódio
- Eric Fogleman

A special thanks to Prof. Boris Murmann for giving permission to use his work and release this package under the Apache 2.0 License.
