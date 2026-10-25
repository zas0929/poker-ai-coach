"""Explicit build/load of the separate exact turn kernel, ABI 2. Never auto-build."""
import argparse
import ctypes as C
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).parent/'native'/'turn_cfr.cpp'
FLAGS = ['-O3','-std=c++17','-ffp-contract=off'] + (['-arch',platform.machine()] if sys.platform=='darwin' else [])


def default_library():
    return Path(tempfile.gettempdir())/'poker-turn-native'/sha256(SOURCE.read_bytes()).hexdigest()[:16]/platform.machine()/('libpoker_turn.dylib' if sys.platform=='darwin' else 'libpoker_turn.so')


def build(output=None):
    compiler = shutil.which('clang++') or shutil.which('g++')
    if not compiler:
        raise RuntimeError('A local C++ compiler is required; nothing is installed automatically.')
    output = Path(output) if output else default_library()
    output.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([compiler,*FLAGS,*(['-dynamiclib'] if sys.platform=='darwin' else ['-shared','-fPIC']),
                    str(SOURCE),'-o',str(output)],check=True,capture_output=True,text=True)
    manifest = {'abi':2,'source_sha256':sha256(SOURCE.read_bytes()).hexdigest(),
                'binary_sha256':sha256(output.read_bytes()).hexdigest(),'flags':FLAGS,
                'architecture':platform.machine(),'library':str(output.resolve())}
    output.with_suffix(output.suffix+'.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def load_library():
    path = Path(os.environ.get('POKER_TURN_NATIVE_LIB',str(default_library())))
    try:
        manifest=json.loads(path.with_suffix(path.suffix+'.json').read_text())
        if (manifest.get('abi')!=2 or manifest.get('flags')!=FLAGS
                or manifest.get('source_sha256')!=sha256(SOURCE.read_bytes()).hexdigest()
                or manifest.get('binary_sha256')!=sha256(path.read_bytes()).hexdigest()):
            raise ValueError('Stale turn kernel.')
    except (OSError,ValueError) as error:
        raise RuntimeError('Turn kernel unavailable; explicitly run research/build_turn_kernel.py.') from error
    lib=C.CDLL(str(path.resolve()));lib.poker_turn_abi.restype=C.c_int
    if lib.poker_turn_abi()!=2:
        raise RuntimeError('Turn kernel ABI mismatch.')
    return lib


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    print(json.dumps(build(args.output)),flush=True)
