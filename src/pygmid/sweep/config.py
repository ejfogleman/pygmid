import glob
import json
import os
import re
import ast
import configparser
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

import numpy as np
import psf_utils


def matrange(start, step, stop):
    num = round((stop - start) / step + 1)
    
    return np.linspace(start, stop, num)

def toupper(optionstr: str) -> str:
    return optionstr.upper()

@dataclass
class SweepConfig(ABC):
    """ Generic, simulator-agnostic sweep configuration base class.

    Subclasses are responsible for all simulator-specific behavior:
    generating the netlist, mapping simulator output signals to lookup-table
    outvars, and parsing simulator output into per-(VGS, VDS) slices.
    """
    config_file_path: str
    _configParser: configparser.ConfigParser = field(default_factory=configparser.ConfigParser, repr=False)
    _config: dict = field(init=False)

    def __post_init__(self):
        self._configParser.optionxform = toupper	
        self._configParser.read(self.config_file_path)
        self._config = {s:dict(self._configParser.items(s)) for s in self._configParser.sections()}
        self._parse_ranges()
        with open(self.netlist_filename, 'w') as netlist_file:
            netlist_file.write(self._generate_netlist())

        self._config['outvars'] = 	['ID','VT','IGD','IGS','GM','GMB','GDS','CGG','CGS','CSG','CGD','CDG','CGB','CDD','CSS']
        self._config['outvars_noise'] = ['STH','SFL']
        n, p, n_noise, p_noise = self._generate_outvars()
        self._config['n'] = n
        self._config['p'] = p
        self._config['n_noise'] = n_noise
        self._config['p_noise'] = p_noise

    def __getitem__(self, key):
        if key not in self._config.keys():
            raise ValueError(f"Lookup table does not contain this data")
    
        return self._config[key]
        
    def _parse_ranges(self):
        # parse numerical ranges		
        for k in ['VGS', 'VDS', 'VSB', 'LENGTH']:
            v = ast.literal_eval(self._config['SWEEP'][k])
            v = [v] if type(v) is not list else v
            v = [matrange(*r) for r in v]
            v = [val for r in v for val in r] 
            self._config['SWEEP'][k] = v
    
        self._config['SWEEP']['WIDTH'] = float(self._config['SWEEP']['WIDTH'])
        self._config['SWEEP']['NFING'] = int(self._config['SWEEP']['NFING'])
    
    def generate_m_dict(self):
        return {
            'INFO' : self._config['MODEL']['INFO'],
            'CORNER' : self._config['MODEL']['CORNER'],
            'TEMP' : float(self._config['MODEL']['TEMP']),
            'NFING' : self._config['SWEEP']['NFING'],
            'L' : np.array(self._config['SWEEP']['LENGTH']).T,
            'W' : self._config['SWEEP']['WIDTH'],
            'VGS' : np.array(self._config['SWEEP']['VGS']).T,
            'VDS' : np.array(self._config['SWEEP']['VDS']).T,
            'VSB' : np.array(self._config['SWEEP']['VSB']).T 
        }
    
    def _write_params(self, **kwargs):
        with open(self.paramfile, 'w') as outfile:
            outfile.write(f"parameters {' '.join([f'{k}={v}' for k, v in kwargs.items()])}")

    @property
    def paramfile(self) -> str:
        """ The filename used for the per-simulation parameter file written by
        `_write_params()` (e.g. sweep length/body-bias values). Defaults to
        the `[MODEL] PARAMFILE` config key, falling back to `params.scs`.

        Subclasses may override this (and `_write_params()`) if their
        simulator requires different syntax/extension (e.g. ngspice's
        `.param` lines vs. Spectre's `parameters` statement).
        """
        return self._config['MODEL'].get('PARAMFILE', 'params.scs')

    @property
    @abstractmethod
    def netlist_filename(self) -> str:
        """ The filename to use for the generated netlist. """
        raise NotImplementedError

    @abstractmethod
    def _generate_netlist(self) -> str:
        """ Generate the netlist for the simulation. """
        raise NotImplementedError

    @abstractmethod
    def _generate_outvars(self, n: list=None, p: list=None, n_noise: list=None, p_noise: list=None) -> tuple[list, list, list, list]:
        """ Generate the mapping of output variables from the simulation to the lookup table. 
        
        outvars: `['ID','VT','IGD','IGS','GM','GMB','GDS','CGG','CGS','CSG','CGD','CDG','CGB','CDD','CSS']`
        outvars_noise: `['STH','SFL']`

        """
        raise NotImplementedError

    @abstractmethod
    def _extract_sweep_params(self, sweep_output_directory, sweep_type="DC"):
        """ Parse simulator output for a single sim directory into per-(VGS, VDS) slices.

        Returns a tuple `(nmos, pmos)` of dicts, keyed by fully-qualified signal
        name (e.g. `mn:ids`), each holding a `len(VGS) x len(VDS)` array.
        """
        raise NotImplementedError


class SpectreConfig(SweepConfig):
    """ Spectre-specific sweep configuration. """

    @property
    def netlist_filename(self) -> str:
        return 'pysweep.scs'

    def _generate_netlist(self) -> str:
        modelfile = self._config['MODEL']['FILE']
        paramfile = self._config['MODEL'].get('PARAMFILE', 'params.scs')
        width = self._config['SWEEP']['WIDTH']
        modelp = self._config['MODEL']['MODELP']
        modeln = self._config['MODEL']['MODELN']
        try:
            mn_supplement = '\\\n\t'.join(json.loads(self._config['MODEL']['MN']))
        except json.decoder.JSONDecodeError:
            raise "Error parsing config: make sure MN has no weird characters in it, and that the list isn't terminated with a trailing ','"
        try:
            mp_supplement = '\\\n\t'.join(json.loads(self._config['MODEL']['MP']))
        except json.decoder.JSONDecodeError:
            raise "Error parsing config: make sure MP has no weird characters in it, and that the list isn't terminated with a trailing ','"
        temp = float(self._config['MODEL']['TEMP'])-273.15
        VDS_max = max(self._config['SWEEP']['VDS'])
        VDS_step = self._config['SWEEP']['VDS'][1] - self._config['SWEEP']['VDS'][0] 
        VGS_max = max(self._config['SWEEP']['VGS'])
        VGS_step = self._config['SWEEP']['VGS'][1] - self._config['SWEEP']['VGS'][0]
    
        NFING = self._config['SWEEP']['NFING']
    
        return '\n'.join((
            f"//pysweep.scs",
            f"include {modelfile}",
            f'include "{paramfile}"\n',   
            f'save *:oppoint',
            f'\n',
            f'parameters gs=0.498 ds=0.2 L=length*1e-6 Wtot={width}e-6 W=500n nf={NFING}',
            f'\n',
            f'vnoi     (vx  0)         vsource dc=0',  
            f'vdsn     (vdn vx)         vsource dc=ds',   
            f'vgsn     (vgn 0)         vsource dc=gs',   
            f'vbsn     (vbn 0)         vsource dc=-sb',  
            f'vdsp     (vdp vx)         vsource dc=-ds',  
            f'vgsp     (vgp 0)         vsource dc=-gs',  
            f'vbsp     (vbp 0)         vsource dc=sb',  
            f'\n',	 
            f'\n',	 
            f'mp (vdp vgp 0 vbp) {modelp} {mp_supplement}',
            f'\n',	 
            f'mn (vdn vgn 0 vbn) {modeln} {mn_supplement}',
            f'\n',	 
            f'simulatorOptions options gmin=1e-13 reltol=1e-4 vabstol=1e-6 iabstol=1e-10 temp={temp} tnom=27',  
            f'sweepvds sweep param=ds start=0 stop={VDS_max} step={VDS_step} {{',  
            f'sweepvgs dc param=gs start=0 stop={VGS_max} step={VGS_step}',  
            f'}}', 
            f'sweepvds_noise sweep param=ds start=0 stop={VDS_max} step={VDS_step} {{', 
            f'	sweepvgs_noise noise freq=1 oprobe=vnoi param=gs start=0 stop={VGS_max} step={VGS_step}', 
            f'}}'
        ))

    def _generate_outvars(self, n: list=None, p: list=None, n_noise: list=None, p_noise: list=None) -> tuple[list, list, list, list]:
        n = [] if n is None else n
        p = [] if p is None else p
        n_noise = [] if n_noise is None else n_noise
        p_noise = [] if p_noise is None else p_noise
        n.append( ['mn:ids','A',   	[1,    0,   0,    0,    0,   0,    0,    0,    0,    0,    0,    0,    0,    0,    0  ]])
        n.append( ['mn:vth','V',   	[0,    1,   0,    0,    0,   0,    0,    0,    0,    0,    0,    0,    0,    0,    0  ]])
        n.append( ['mn:igd','A',   	[0,    0,   1,    0,    0,   0,    0,    0,    0,    0,    0,    0,    0,    0,    0  ]])
        n.append( ['mn:igs','A',   	[0,    0,   0,    1,    0,   0,    0,    0,    0,    0,    0,    0,    0,    0,    0  ]])
        n.append( ['mn:gm','S',    	[0,    0,   0,    0,    1,   0,    0,    0,    0,    0,    0,    0,    0,    0,    0  ]])
        n.append( ['mn:gmbs','S',  	[0,    0,   0,    0,    0,   1,    0,    0,    0,    0,    0,    0,    0,    0,    0  ]])
        n.append( ['mn:gds','S',   	[0,    0,   0,    0,    0,   0,    1,    0,    0,    0,    0,    0,    0,    0,    0  ]])
        n.append( ['mn:cgg','F',   	[0,    0,   0,    0,    0,   0,    0,    1,    0,    0,    0,    0,    0,    0,    0  ]])
        n.append( ['mn:cgs','F',   	[0,    0,   0,    0,    0,   0,    0,    0,   -1,    0,    0,    0,    0,    0,    0  ]])
        n.append( ['mn:cgd','F',   	[0,    0,   0,    0,    0,   0,    0,    0,    0,    0,   -1,    0,    0,    0,    0  ]])
        n.append( ['mn:cgb','F',   	[0,    0,   0,    0,    0,   0,    0,    0,    0,    0,    0,    0,   -1,    0,    0  ]])
        n.append( ['mn:cdd','F',   	[0,    0,   0,    0,    0,   0,    0,    0,    0,    0,    0,    0,    0,    1,    0  ]])
        n.append( ['mn:cdg','F',   	[0,    0,   0,    0,    0,   0,    0,    0,    0,    0,    0,   -1,    0,    0,    0  ]])
        n.append( ['mn:css','F',   	[0,    0,   0,    0,    0,   0,    0,    0,    0,    0,    0,    0,    0,    0,    1  ]])
        n.append( ['mn:csg','F',   	[0,    0,   0,    0,    0,   0,    0,    0,    0,   -1,    0,    0,    0,    0,    0  ]])
        n.append( ['mn:cjd','F',   	[0,    0,   0,    0,    0,   0,    0,    0,    0,    0,    0,    0,    0,    1,    0  ]])
        n.append( ['mn:cjs','F',   	[0,    0,   0,    0,    0,   0,    0,    0,    0,    0,    0,    0,    0,    0,    1  ]])

        p.append( ['mp:ids','A',   	[-1,    0,    0,    0,    0,   0,    0,    0,    0,    0,    0,    0,    0,    0,    0  ]])
        p.append( ['mp:vth','V',   	[ 0,   -1,    0,    0,    0,   0,    0,    0,    0,    0,    0,    0,    0,    0,    0  ]])
        p.append( ['mp:igd','A',   	[ 0,    0,   -1,    0,    0,   0,    0,    0,    0,    0,    0,    0,    0,    0,    0  ]])
        p.append( ['mp:igs','A',   	[ 0,    0,    0,   -1,    0,   0,    0,    0,    0,    0,    0,    0,    0,    0,    0  ]])
        p.append( ['mp:gm','S',    	[ 0,    0,    0,    0,    1,   0,    0,    0,    0,    0,    0,    0,    0,    0,    0  ]])
        p.append( ['mp:gmbs','S',  	[ 0,    0,    0,    0,    0,   1,    0,    0,    0,    0,    0,    0,    0,    0,    0  ]])
        p.append( ['mp:gds','S',   	[ 0,    0,    0,    0,    0,   0,    1,    0,    0,    0,    0,    0,    0,    0,    0  ]])
        p.append( ['mp:cgg','F',   	[ 0,    0,    0,    0,    0,   0,    0,    1,    0,    0,    0,    0,    0,    0,    0  ]])
        p.append( ['mp:cgs','F',   	[ 0,    0,    0,    0,    0,   0,    0,    0,   -1,    0,    0,    0,    0,    0,    0  ]])
        p.append( ['mp:cgd','F',   	[ 0,    0,    0,    0,    0,   0,    0,    0,    0,    0,   -1,    0,    0,    0,    0  ]])
        p.append( ['mp:cgb','F',   	[ 0,    0,    0,    0,    0,   0,    0,    0,    0,    0,    0,    0,   -1,    0,    0  ]])
        p.append( ['mp:cdd','F',   	[ 0,    0,    0,    0,    0,   0,    0,    0,    0,    0,    0,    0,    0,    1,    0  ]])
        p.append( ['mp:cdg','F',   	[ 0,    0,    0,    0,    0,   0,    0,    0,    0,    0,    0,   -1,    0,    0,    0  ]])
        p.append( ['mp:css','F',   	[ 0,    0,    0,    0,    0,   0,    0,    0,    0,    0,    0,    0,    0,    0,    1  ]])
        p.append( ['mp:csg','F',   	[ 0,    0,    0,    0,    0,   0,    0,    0,    0,   -1,    0,    0,    0,    0,    0  ]])
        p.append( ['mp:cjd','F',   	[ 0,    0,    0,    0,    0,   0,    0,    0,    0,    0,    0,    0,    0,    1,    0  ]])
        p.append( ['mp:cjs','F',   	[ 0,    0,    0,    0,    0,   0,    0,    0,    0,    0,    0,    0,    0,    0,    1  ]])
        
        n_noise.append(['mn:id', '', [1, 0]])
        n_noise.append(['mn:fn', '', [0, 1]])
        
        p_noise.append(['mp:id', '', [1, 0]])
        p_noise.append(['mp:fn', '', [0, 1]])
        return (n, p, n_noise, p_noise)

    @staticmethod
    def _extract_number_regex(string):
        pattern = r'\d+'  # Matches one or more digits
        match = re.search(pattern, string)
        if match:
            return int(match.group())  # Extracted number as an integer
        else:
            return None

    def _extract_sweep_params(self, sweep_output_directory, sweep_type="DC"):
        """
        Params  -> list of strings
        size    -> len(VGS) x len(VDS)
        """
        if sweep_type == "DC":
            filename_pattern = 'sweepvds-*_sweepvgs.dc'
            params = [ ':'.join(k[0].split(':')[1:]) for k in self._config['n'] ]
        elif sweep_type == "NOISE":
            filename_pattern = 'sweepvds_noise-*_sweepvgs_noise.noise'
            params = [ ':'.join(k[0].split(':')[1:]) for k in self._config['n_noise'] ]
        else:
            raise ValueError(f"Unknown sweep type: {sweep_type}. Must be 'DC' or 'NOISE'.")

        file_paths = glob.glob(os.path.join(sweep_output_directory, filename_pattern))
        # remove directory in case it contains number. Only want to sort based on filename itself
        filelist = sorted([os.path.basename(f) for f in file_paths], key=self._extract_number_regex)
        
        nmos = {f"mn:{param}" : np.zeros((len(self._config['SWEEP']['VGS']), len(self._config['SWEEP']['VDS']))) for param in params}
        pmos = {f"mp:{param}" : np.zeros((len(self._config['SWEEP']['VGS']), len(self._config['SWEEP']['VDS']))) for param in params}
        for VDS_i, f in enumerate(filelist):
            # reconstruct path
            file_path = os.path.join(sweep_output_directory, f)
            # need to extract parameter from PSFs
            psf = psf_utils.PSF( file_path )
            
            for param in params:
                nmos[f'mn:{param}'][:,VDS_i] = (psf.get_signal(f"mn:{param}").ordinate).T
                pmos[f'mp:{param}'][:,VDS_i] = (psf.get_signal(f"mp:{param}").ordinate).T
        
        return (nmos, pmos)


class NgspiceConfig(SweepConfig):
    """ ngspice-specific sweep configuration.

    Both devices get independently-biased, real-polarity sources
    (`Vgs_p`/`Vds_p`/`Vbs_p` negative) tied directly to ground -- the same
    real-bias scheme `SpectreConfig` uses (its `vx`/`vnoi` common node is
    only a noise-current sense point, DC-transparent, not a mirrored bias
    topology). Despite that structural similarity, ngspice was found
    (empirically, against ngspice-43/KLU) to report `id`/`vth` for PMOS in
    *positive* convention here, unlike Spectre's `mp:ids`/`mp:vth`, which
    need a `-1` coefficient. The cause appears to be a simulator-internal
    op-point reporting convention rather than anything netlist-topology
    related -- see the `p` coefficient table in `_generate_outvars()`.
    """

    # Raw @mn[...]/@mp[...] DC operating-point quantities saved via `wrdata`,
    # in the fixed order shared between netlist generation (the `wrdata`
    # argument list) and parsing (`_extract_sweep_params()`'s column order)
    # so the two can never drift out of sync. Excludes igd/igs: they read
    # 0.0 under nearly all models (need `igcmod=1`, and even then only the
    # charge-based igcd/igcs split reliably comes back nonzero) -- IGD/IGS
    # outvars are left zero-filled for Phase 1 rather than wired to an
    # unreliable signal.
    _DC_PARAMS = ['id', 'vth', 'gm', 'gmbs', 'gds',
                  'cgg', 'cgs', 'cgd', 'cgb', 'cdd', 'cdg', 'css', 'csg',
                  'capbd', 'capbs']

    @property
    def netlist_filename(self) -> str:
        return 'pysweep.cir'

    @property
    def paramfile(self) -> str:
        return self._config['MODEL'].get('PARAMFILE', 'params.lib')

    def _write_params(self, **kwargs):
        with open(self.paramfile, 'w') as outfile:
            outfile.write('\n'.join(f'.param {k}={v}' for k, v in kwargs.items()))

    def _extra_includes(self) -> list:
        """ `.include` lines for auxiliary files a PDK's model needs beyond
        the main `[MODEL] FILE`/`LIBNAME` include -- e.g. gf180mcuD's
        `design.ngspice`, which defines `sw_stat_mismatch`/`sw_stat_global`
        referenced by the model body and is otherwise left undefined.
        Optional `[MODEL] EXTRA_INCLUDE` config key, a JSON list of paths,
        mirroring the existing `MN`/`MP` supplement convention. Resolved to
        absolute paths for the same reason `modelfile`/`paramfile` are in
        `_generate_netlist()`.
        """
        try:
            paths = json.loads(self._config['MODEL'].get('EXTRA_INCLUDE', '[]'))
        except json.decoder.JSONDecodeError:
            raise ValueError("Error parsing config: EXTRA_INCLUDE must be a JSON list of paths, with no trailing ','")
        return [f'.include {os.path.abspath(p)}' for p in paths]

    def _generate_netlist(self) -> str:
        # Resolved to absolute paths: `NgspiceSimulator` runs ngspice with
        # the per-point output directory as its working directory (ngspice's
        # `wrdata` targets are plain relative filenames baked into this
        # netlist once -- unlike Spectre's `-raw` flag, there's no way to
        # redirect them without changing cwd), so any relative `.include`
        # here would resolve against the wrong directory once that happens.
        modelfile = os.path.abspath(self._config['MODEL']['FILE'])
        libname = self._config['MODEL'].get('LIBNAME')
        # PDK model files are typically wrapped in `.lib libname ... .endl
        # libname`, which needs ngspice's `.lib file libname` form (Spectre's
        # `FILE = "..." section=NN` suffix syntax doesn't apply here). A
        # plain `.param`/`.model`-only file with no `.lib` wrapper works with
        # a plain `.include` instead -- set `[MODEL] LIBNAME` only when the
        # model file has the wrapper.
        model_include = (f'.lib {modelfile} {libname}' if libname
                          else f'.include {modelfile}')

        width = self._config['SWEEP']['WIDTH']
        NFING = self._config['SWEEP']['NFING']
        modeln = self._config['MODEL']['MODELN']
        modelp = self._config['MODEL']['MODELP']
        try:
            mn_supplement = ' '.join(json.loads(self._config['MODEL']['MN']))
        except json.decoder.JSONDecodeError:
            raise "Error parsing config: make sure MN has no weird characters in it, and that the list isn't terminated with a trailing ','"
        try:
            mp_supplement = ' '.join(json.loads(self._config['MODEL']['MP']))
        except json.decoder.JSONDecodeError:
            raise "Error parsing config: make sure MP has no weird characters in it, and that the list isn't terminated with a trailing ','"

        temp = float(self._config['MODEL']['TEMP']) - 273.15
        VDS_max = max(self._config['SWEEP']['VDS'])
        VDS_step = self._config['SWEEP']['VDS'][1] - self._config['SWEEP']['VDS'][0]
        VGS_max = max(self._config['SWEEP']['VGS'])
        VGS_step = self._config['SWEEP']['VGS'][1] - self._config['SWEEP']['VGS'][0]

        n_probe = ' '.join(f'@mn[{p}]' for p in self._DC_PARAMS)
        p_probe = ' '.join(f'@mp[{p}]' for p in self._DC_PARAMS)

        return '\n'.join((
            '* pysweep.cir',
            *self._extra_includes(),
            model_include,
            f'.include {os.path.abspath(self.paramfile)}',
            '',
            f'Vgs_n gate_n 0 dc 0.498',
            f'Vds_n drain_n 0 dc 0.2',
            f'Vbs_n bulk_n 0 dc {{-sb}}',
            '',
            f'Vgs_p gate_p 0 dc -0.498',
            f'Vds_p drain_p 0 dc -0.2',
            f'Vbs_p bulk_p 0 dc {{sb}}',
            '',
            f'Mn drain_n gate_n 0 bulk_n {modeln} L={{length*1e-6}} W={width}u nf={NFING} {mn_supplement}',
            f'Mp drain_p gate_p 0 bulk_p {modelp} L={{length*1e-6}} W={width}u nf={NFING} {mp_supplement}',
            '',
            f'.options temp={temp} tnom=27',
            '.control',
            f'save all {n_probe}',
            f'dc Vgs_n 0 {VGS_max} {VGS_step} Vds_n 0 {VDS_max} {VDS_step}',
            f'wrdata mn.txt {n_probe}',
            f'save all {p_probe}',
            f'dc Vgs_p 0 {-VGS_max} {-VGS_step} Vds_p 0 {-VDS_max} {-VDS_step}',
            f'wrdata mp.txt {p_probe}',
            '.endc',
            '.end',
        ))

    def _generate_outvars(self, n: list=None, p: list=None, n_noise: list=None, p_noise: list=None) -> tuple[list, list, list, list]:
        n = [] if n is None else n
        p = [] if p is None else p
        n_noise = [] if n_noise is None else n_noise
        p_noise = [] if p_noise is None else p_noise

        # outvars index:      ID   VT  IGD  IGS   GM  GMB  GDS  CGG  CGS  CSG  CGD  CDG  CGB  CDD  CSS
        n.append( ['mn:id',   'A', [1,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0 ]])
        n.append( ['mn:vth',  'V', [0,   1,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0 ]])
        n.append( ['mn:gm',   'S', [0,   0,   0,   0,   1,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0 ]])
        n.append( ['mn:gmbs', 'S', [0,   0,   0,   0,   0,   1,   0,   0,   0,   0,   0,   0,   0,   0,   0 ]])
        n.append( ['mn:gds',  'S', [0,   0,   0,   0,   0,   0,   1,   0,   0,   0,   0,   0,   0,   0,   0 ]])
        n.append( ['mn:cgg',  'F', [0,   0,   0,   0,   0,   0,   0,   1,   0,   0,   0,   0,   0,   0,   0 ]])
        n.append( ['mn:cgs',  'F', [0,   0,   0,   0,   0,   0,   0,   0,  -1,   0,   0,   0,   0,   0,   0 ]])
        n.append( ['mn:cgd',  'F', [0,   0,   0,   0,   0,   0,   0,   0,   0,   0,  -1,   0,   0,   0,   0 ]])
        n.append( ['mn:cgb',  'F', [0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,  -1,   0,   0 ]])
        n.append( ['mn:cdd',  'F', [0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   1,   0 ]])
        n.append( ['mn:cdg',  'F', [0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,  -1,   0,   0,   0 ]])
        n.append( ['mn:css',  'F', [0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   1 ]])
        n.append( ['mn:csg',  'F', [0,   0,   0,   0,   0,   0,   0,   0,   0,  -1,   0,   0,   0,   0,   0 ]])
        n.append( ['mn:capbd','F', [0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   1,   0 ]])
        n.append( ['mn:capbs','F', [0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   1 ]])

        # ngspice reports PMOS id/vth in *positive* convention here (verified
        # empirically) -- do not copy SpectreConfig.p's -1 coefficients for
        # these two, or values would be double-negated. This isn't a netlist
        # topology difference (both simulators use the same real, per-device
        # bias scheme); it appears to be a simulator-internal op-point
        # reporting convention. Cap signs, by contrast, were verified
        # numerically identical to the NMOS row above, so they keep the same
        # pattern as SpectreConfig.p.
        p.append( ['mp:id',   'A', [1,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0 ]])
        p.append( ['mp:vth',  'V', [0,   1,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0 ]])
        p.append( ['mp:gm',   'S', [0,   0,   0,   0,   1,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0 ]])
        p.append( ['mp:gmbs', 'S', [0,   0,   0,   0,   0,   1,   0,   0,   0,   0,   0,   0,   0,   0,   0 ]])
        p.append( ['mp:gds',  'S', [0,   0,   0,   0,   0,   0,   1,   0,   0,   0,   0,   0,   0,   0,   0 ]])
        p.append( ['mp:cgg',  'F', [0,   0,   0,   0,   0,   0,   0,   1,   0,   0,   0,   0,   0,   0,   0 ]])
        p.append( ['mp:cgs',  'F', [0,   0,   0,   0,   0,   0,   0,   0,  -1,   0,   0,   0,   0,   0,   0 ]])
        p.append( ['mp:cgd',  'F', [0,   0,   0,   0,   0,   0,   0,   0,   0,   0,  -1,   0,   0,   0,   0 ]])
        p.append( ['mp:cgb',  'F', [0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,  -1,   0,   0 ]])
        p.append( ['mp:cdd',  'F', [0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   1,   0 ]])
        p.append( ['mp:cdg',  'F', [0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,  -1,   0,   0,   0 ]])
        p.append( ['mp:css',  'F', [0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   1 ]])
        p.append( ['mp:csg',  'F', [0,   0,   0,   0,   0,   0,   0,   0,   0,  -1,   0,   0,   0,   0,   0 ]])
        p.append( ['mp:capbd','F', [0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   1,   0 ]])
        p.append( ['mp:capbs','F', [0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   1 ]])

        # Noise is deferred for Phase 1 (ngspice's `noise` analysis exposes
        # total output noise rather than Spectre-style per-source
        # contributions, making an STH/SFL decomposition harder). Stub rows
        # with zero coefficients keep Sweep.run()'s unconditional noise
        # accumulation loop working without a real noise analysis; see the
        # matching stub in `_extract_sweep_params()`.
        n_noise.append(['mn:noise_stub', '', [0, 0]])
        p_noise.append(['mp:noise_stub', '', [0, 0]])
        return (n, p, n_noise, p_noise)

    def _extract_sweep_params(self, sweep_output_directory, sweep_type="DC"):
        """
        Params  -> list of strings
        size    -> len(VGS) x len(VDS)
        """
        n_vgs = len(self._config['SWEEP']['VGS'])
        n_vds = len(self._config['SWEEP']['VDS'])

        if sweep_type == "DC":
            nmos = self._read_wrdata(os.path.join(sweep_output_directory, 'mn.txt'), 'mn', n_vgs, n_vds)
            pmos = self._read_wrdata(os.path.join(sweep_output_directory, 'mp.txt'), 'mp', n_vgs, n_vds)
            return (nmos, pmos)
        elif sweep_type == "NOISE":
            zeros = np.zeros((n_vgs, n_vds))
            return ({'mn:noise_stub': zeros}, {'mp:noise_stub': zeros})
        else:
            raise ValueError(f"Unknown sweep type: {sweep_type}. Must be 'DC' or 'NOISE'.")

    @classmethod
    def _read_wrdata(cls, file_path, prefix, n_vgs, n_vds):
        # wrdata interleaves a (redundant) scale column ahead of each
        # requested vector's value column; drop the scale columns.
        values = np.loadtxt(file_path)[:, 1::2]
        return {
            f'{prefix}:{param}': values[:, k].reshape((n_vds, n_vgs)).T
            for k, param in enumerate(cls._DC_PARAMS)
        }


class SubcircuitNgspiceConfig(NgspiceConfig):
    """ ngspice sweep configuration for PDK devices that wrap their BSIM4
    core model in a `.subckt` (sky130, gf180mcuD) rather than exposing a
    flat M-instance the way `NgspiceConfig` assumes. Emits `X`-prefixed
    instances and probes the internal MOSFET the subcircuit expands to via
    `@m.<Xinst>.<name>[param]` instead of `@mn[param]`.

    The ad/as/pd/ps/nrd/nrs junction-geometry formula in `_instance_tail()`
    is shared across subclasses -- verified identical in shape (differing
    only by one PDK-specific diffusion-spacing constant) against two real,
    currently-used proc_char testbenches: `tb_ejf_sacomp.spice` (sky130)
    and `tb_gf180mcu.spice` (gf180mcuD). Probe paths, the sign of PMOS
    id/vth (unchanged `+1`, same as the flat device -- inherited from
    `NgspiceConfig._generate_outvars()`), and the unit conventions each
    subclass declares were all confirmed with a real `ngspice -b` run
    against `~/.ciel/sky130B`/`~/.ciel/gf180mcuD`.
    """

    @property
    @abstractmethod
    def _diffusion_spacing(self) -> float:
        """ Contact-to-gate diffusion spacing (um) used in the shared
        ad/as/pd/ps/nrd/nrs formula below. sky130: 0.29, gf180: 0.18.
        """
        raise NotImplementedError

    @abstractmethod
    def _geom(self, value: float) -> str:
        """ Render a um-valued length/area/perimeter number in this PDK's
        convention: bare (sky130 -- relies on the target model file's own
        `.options parser scale=1.0u`, pulled in transitively via the
        standard `.lib sky130.lib.spice <corner>` include) or `u`-suffixed
        (gf180 -- no such directive available). Used for W/ad/as/pd/ps;
        NOT for nrd/nrs, which are dimensionless ratios (spacing/width)
        and never need a unit suffix either way.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def _length_expr(self) -> str:
        """ ngspice expression for the per-point-swept L=, in this PDK's
        unit convention. Must stay symbolic -- it references the {length}
        `.param` `_write_params()` rewrites per sweep point, and the
        netlist is only generated once (`SweepConfig.__post_init__`), so
        this can never be resolved to a Python float at netlist-generation
        time. sky130: '{length}' (bare, scale-parser handles it). gf180:
        '{length*1e-6}' (explicit meters -- matches how `NgspiceConfig`'s
        own flat L= already works, since gf180 has no scale-parser).
        """
        raise NotImplementedError

    @abstractmethod
    def _internal_probe_name(self, modelname: str) -> str:
        """ Lowercase name of the M-device ngspice exposes inside the
        expanded X-instance subcircuit, for @m.<Xinst>.<name>[param]
        probing.
        """
        raise NotImplementedError

    def _instance_tail(self, width, nf) -> str:
        spacing = self._diffusion_spacing
        ad = int((nf+1)/2) * width/nf * spacing
        as_ = int((nf+2)/2) * width/nf * spacing
        pd = 2*int((nf+1)/2) * (width/nf + spacing)
        ps = 2*int((nf+2)/2) * (width/nf + spacing)
        nrd = nrs = spacing / width
        return (f"W={self._geom(width)} nf={nf} "
                f"ad={self._geom(ad)} as={self._geom(as_)} "
                f"pd={self._geom(pd)} ps={self._geom(ps)} "
                f"nrd={nrd} nrs={nrs} sa=0 sb=0 sd=0")

    def _generate_netlist(self) -> str:
        modelfile = os.path.abspath(self._config['MODEL']['FILE'])
        libname = self._config['MODEL'].get('LIBNAME')
        model_include = (f'.lib {modelfile} {libname}' if libname
                          else f'.include {modelfile}')

        width = self._config['SWEEP']['WIDTH']
        NFING = self._config['SWEEP']['NFING']
        modeln = self._config['MODEL']['MODELN']
        modelp = self._config['MODEL']['MODELP']
        try:
            mn_supplement = ' '.join(json.loads(self._config['MODEL']['MN']))
        except json.decoder.JSONDecodeError:
            raise "Error parsing config: make sure MN has no weird characters in it, and that the list isn't terminated with a trailing ','"
        try:
            mp_supplement = ' '.join(json.loads(self._config['MODEL']['MP']))
        except json.decoder.JSONDecodeError:
            raise "Error parsing config: make sure MP has no weird characters in it, and that the list isn't terminated with a trailing ','"

        temp = float(self._config['MODEL']['TEMP']) - 273.15
        VDS_max = max(self._config['SWEEP']['VDS'])
        VDS_step = self._config['SWEEP']['VDS'][1] - self._config['SWEEP']['VDS'][0]
        VGS_max = max(self._config['SWEEP']['VGS'])
        VGS_step = self._config['SWEEP']['VGS'][1] - self._config['SWEEP']['VGS'][0]

        n_probe = ' '.join(f'@m.xmn.{self._internal_probe_name(modeln)}[{p}]' for p in self._DC_PARAMS)
        p_probe = ' '.join(f'@m.xmp.{self._internal_probe_name(modelp)}[{p}]' for p in self._DC_PARAMS)

        return '\n'.join((
            '* pysweep.cir',
            *self._extra_includes(),
            model_include,
            f'.include {os.path.abspath(self.paramfile)}',
            '',
            f'Vgs_n gate_n 0 dc 0.498',
            f'Vds_n drain_n 0 dc 0.2',
            f'Vbs_n bulk_n 0 dc {{-sb}}',
            '',
            f'Vgs_p gate_p 0 dc -0.498',
            f'Vds_p drain_p 0 dc -0.2',
            f'Vbs_p bulk_p 0 dc {{sb}}',
            '',
            f'Xmn drain_n gate_n 0 bulk_n {modeln} L={self._length_expr} {self._instance_tail(width, NFING)} {mn_supplement}',
            f'Xmp drain_p gate_p 0 bulk_p {modelp} L={self._length_expr} {self._instance_tail(width, NFING)} {mp_supplement}',
            '',
            f'.options temp={temp} tnom=27',
            '.control',
            f'save all {n_probe}',
            f'dc Vgs_n 0 {VGS_max} {VGS_step} Vds_n 0 {VDS_max} {VDS_step}',
            f'wrdata mn.txt {n_probe}',
            f'save all {p_probe}',
            f'dc Vgs_p 0 {-VGS_max} {-VGS_step} Vds_p 0 {-VDS_max} {-VDS_step}',
            f'wrdata mp.txt {p_probe}',
            '.endc',
            '.end',
        ))


class NgspiceSky130Config(SubcircuitNgspiceConfig):
    """ SkyWater sky130 (`sky130_fd_pr__nfet_01v8`/`pfet_01v8`). Bare-um
    length units -- relies on `.options parser scale=1.0u`, which the
    standard `.lib sky130.lib.spice <corner>` include (set via `[MODEL]
    LIBNAME`) pulls in transitively. Verified against `~/.ciel/sky130B`
    and a real proc_char testbench (`tb_ejf_sacomp.spice`).
    """

    @property
    def _diffusion_spacing(self) -> float:
        return 0.29

    def _geom(self, value: float) -> str:
        return f"{value}"

    @property
    def _length_expr(self) -> str:
        return '{length}'

    def _internal_probe_name(self, modelname: str) -> str:
        return f"m{modelname.lower()}"


class NgspiceGf180Config(SubcircuitNgspiceConfig):
    """ GlobalFoundries gf180mcuD (`nfet_03v3`/`pfet_03v3`). Raw-meter
    length units (explicit `u` suffixes) -- no scale-parser directive
    available, unlike sky130. Verified against `~/.ciel/gf180mcuD` and a
    real proc_char testbench (`tb_gf180mcu.spice`). Requires `[MODEL]
    EXTRA_INCLUDE` pointed at the PDK's `design.ngspice` (defines
    `sw_stat_mismatch`/`sw_stat_global`, referenced by the model body and
    otherwise left undefined). The `m=1` multiplier the PDK subckt exposes
    goes through the existing `[MODEL] MN`/`MP` supplement, not a
    dedicated hook.
    """

    @property
    def _diffusion_spacing(self) -> float:
        return 0.18

    def _geom(self, value: float) -> str:
        return f"{value}u"

    @property
    def _length_expr(self) -> str:
        return '{length*1e-6}'

    def _internal_probe_name(self, modelname: str) -> str:
        return "m0"


# Backward-compatible alias: existing configs/imports referring to `Config`
# continue to work unchanged.
Config = SpectreConfig
