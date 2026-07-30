import os
import subprocess
import logging
from typing import Protocol, runtime_checkable


@runtime_checkable
class Simulator(Protocol):
    """ Structural interface every simulator backend must satisfy.

    Backends are not required to subclass this -- any object providing a
    settable `directory` property and a `run(filename)` method satisfies
    the contract (see `SpectreSimulator` below).
    """

    @property
    def directory(self) -> str:
        ...

    @directory.setter
    def directory(self, dir: str) -> None:
        ...

    def run(self, filename: str):
        """ Run the simulator on `filename`, returning the output directory
        (or a falsy value on failure). """
        ...


class SpectreSimulator:
    def __init__(self, *args):
        self.__args = list(args)
    
    @property
    def directory(self):
        return self.__args[-1]
    
    @directory.setter
    def directory(self, dir):
        self.__args[-1] = dir

    def run(self, filename: str):
        infile = filename
        try:
            cmd_args = ['spectre', filename] + [*self.__args]
            cp = subprocess.run(cmd_args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            logging.info(f"Error executing process\n\n{e}")
            return

        return self.__args[-1]


class NgspiceSimulator:
    """ ngspice batch-mode (`ngspice -b`) backend.

    Unlike Spectre's `-raw <dir>` flag (decoupled from the netlist itself),
    ngspice's `wrdata` output paths are plain relative filenames baked into
    the netlist once at config-generation time (see
    `NgspiceConfig._generate_netlist()`). Per-run output isolation is done
    by running ngspice with `directory` as the subprocess's working
    directory instead -- `NgspiceConfig` resolves its own `.include`s to
    absolute paths so they keep working once cwd moves.
    """
    def __init__(self, directory: str = '.'):
        self.__directory = directory

    @property
    def directory(self):
        return self.__directory

    @directory.setter
    def directory(self, dir):
        self.__directory = dir

    def run(self, filename: str):
        netlist_path = os.path.abspath(filename)
        os.makedirs(self.__directory, exist_ok=True)
        try:
            cp = subprocess.run(
                ['ngspice', '-b', netlist_path],
                cwd=self.__directory,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            logging.info(f"Error executing process\n\n{e}")
            return

        return self.__directory