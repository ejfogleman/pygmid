import concurrent.futures
import multiprocessing as mp
import os
import pickle
import shutil
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from warnings import warn

import numpy as np
from tqdm import tqdm

from .config import Config, SweepConfig
from .simulator import SpectreSimulator

SPECTRE_ARGS = ['+escchars', 
        '=log', 
        './sweep/psf/spectre.out', 
        '-format', 
        'psfascii', 
        '-raw', 
        './sweep/psf']


@dataclass
class Sweep:
    config_file_path: str
    _config: SweepConfig | None = field(default_factory=lambda: None, repr=False)
    _simulator: SpectreSimulator = field(default_factory=lambda: SpectreSimulator(*SPECTRE_ARGS), repr=False)
    def __post_init__(self):
        for f in filter(lambda p: p.suffix == ".py", map(lambda p: Path(p), os.listdir(os.getcwd()))):
            # Import the file and check if it has a class that is a subclass of Config
            module_name = f.stem
            module = import_module(module_name)
            try:
                cls = next(filter(lambda c: isinstance(c, type) and issubclass(c, SweepConfig) and c != SweepConfig, map(lambda n: getattr(module, n), filter(lambda n: not n.startswith("__") and not n.endswith("__"), dir(module)))))
                self._config = cls(self.config_file_path)
                print(f"Loaded config from {f.stem}{f.suffix}")
                #print(f"{self._config=}")
                break
            except StopIteration:
                pass

        if self._config is None:
            warn("No Config subclass found in the current directory. Using default Config class.", ImportWarning)
            self._config = Config(self.config_file_path)
    
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
