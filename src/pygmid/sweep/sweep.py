import concurrent.futures
import configparser
import multiprocessing as mp
import os
import pickle
import shutil
from dataclasses import dataclass, field

import numpy as np
from tqdm import tqdm

from .config import SweepConfig
from .registry import SPECTRE_ARGS, get_simulator_backend
from .simulator import Simulator, SpectreSimulator

DEFAULT_SIMULATOR_NAME = 'spectre'


def _read_simulator_name(config_file_path: str) -> str:
    """ Peek at the `[MODEL] simulator` key of the config file, without
    running the (potentially simulator-specific) full config parse.

    Defaults to `'spectre'` if the key is absent, preserving behavior for
    existing config files that predate the `simulator` key.
    """
    parser = configparser.ConfigParser()
    parser.optionxform = str.upper
    parser.read(config_file_path)
    return parser.get('MODEL', 'SIMULATOR', fallback=DEFAULT_SIMULATOR_NAME)


@dataclass
class Sweep:
    config_file_path: str
    _config: SweepConfig | None = field(default=None, repr=False)
    _simulator: Simulator | None = field(default=None, repr=False)
    def __post_init__(self):
        if self._config is not None:
            # Config supplied explicitly (e.g. by tests): only fill in a
            # default simulator if one wasn't also supplied explicitly.
            if self._simulator is None:
                self._simulator = SpectreSimulator(*SPECTRE_ARGS)
            return

        simulator_name = _read_simulator_name(self.config_file_path)
        config_cls, simulator_factory = get_simulator_backend(simulator_name)
        self._config = config_cls(self.config_file_path)
        if self._simulator is None:
            self._simulator = simulator_factory()
    
    def run(self):
        
        Ls = self._config['SWEEP']['LENGTH']
        VSBs = self._config['SWEEP']['VSB']

        nch = self._config.generate_m_dict()
        pch = self._config.generate_m_dict()
        dimshape = (len(Ls),len(nch['VGS']),len(nch['VDS']),len(VSBs))
        for outvar in self._config['outvars']:
            nch[outvar] = np.zeros(dimshape, order='F')
            pch[outvar] = np.zeros(dimshape, order='F')

        for outvar in self._config['outvars_noise']:
            nch[outvar] = np.zeros(dimshape, order='F')
            pch[outvar] = np.zeros(dimshape, order='F')
        
        with concurrent.futures.ProcessPoolExecutor(max_workers=mp.cpu_count()) as executor:
            # A list to store futures for data parsing
            futures = []
            for i, L in enumerate(tqdm(Ls,desc="Sweeping L")):
                for j, VSB in enumerate(tqdm(VSBs, desc="Sweeping VSB", leave=False)):
                    self._config._write_params(length=L, sb=VSB)
                    
                    sim_path = f"./sweep/psf_{i}_{j}"
                    self._simulator.directory = sim_path
                    cp = self._simulator.run(self._config.netlist_filename)

                    futures.append(executor.submit(self.parse_sim, *[sim_path]))
            
            concurrent.futures.wait(futures)

        for f in futures:
            i, j , n_dict, p_dict, nn_dict, pn_dict = f.result()
            for n,p in zip(self._config['n'],self._config['p']):
                params_n = n
                values_n = n_dict[params_n[0]]
                params_p = p
                values_p = p_dict[params_p[0]]
                for m, outvar in enumerate(self._config['outvars']):
                    nch[outvar][i,:,:,j] += np.squeeze(values_n*params_n[2][m])
                    pch[outvar][i,:,:,j] += np.squeeze(values_p*params_p[2][m])

            for n,p in zip(self._config['n_noise'],self._config['p_noise']):
                params_n = n
                values_n = nn_dict[params_n[0]]
                params_p = p
                values_p = pn_dict[params_p[0]]
                for m, outvar in enumerate(self._config['outvars_noise']):
                    nch[outvar][i,:,:,j] += np.squeeze(values_n*params_n[2][m])
                    pch[outvar][i,:,:,j] += np.squeeze(values_p*params_p[2][m])
        
        self._cleanup()
        # then save data to file
        modeln_file_path = f"{self._config['MODEL']['SAVEFILEN']}.pkl"
        modelp_file_path = f"{self._config['MODEL']['SAVEFILEP']}.pkl"
        with open(modeln_file_path, 'wb') as f:
            pickle.dump(nch, f)
        with open(modelp_file_path, 'wb') as f:
            pickle.dump(pch, f)
        return (modeln_file_path, modelp_file_path)
    
    def parse_sim(self, filepath):
        
        fileparts = filepath.split("_")
        i = int(fileparts[-2])
        j = int(fileparts[-1])
        
        (n_dict, p_dict) = self._config._extract_sweep_params(filepath)
        
        (nn_dict, pn_dict) = self._config._extract_sweep_params(filepath, sweep_type="NOISE")

        return i, j, n_dict, p_dict, nn_dict, pn_dict
    
    def _cleanup(self):
        try:
            shutil.rmtree("./sweep")
            os.remove(self._config.netlist_filename)
            os.remove("params.scs")
        except OSError as e:
            print("Could not perform cleanup:\nFile - {e.filename}\nError - {e.strerror}")
