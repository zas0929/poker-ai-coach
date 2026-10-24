"""Explicit local build of our research C++ kernel; no downloads or auto-install."""
import argparse
from hashlib import sha256
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SOURCE=Path(__file__).parent/'native'/'cfr.cpp'
FLAGS=['-O3','-std=c++17','-ffp-contract=off']+(['-arch',platform.machine()] if sys.platform=='darwin' else [])

def default_library():
    return Path(tempfile.gettempdir())/'poker-cfr-native'/sha256(SOURCE.read_bytes()).hexdigest()[:16]/platform.machine()/('libpoker_cfr.dylib' if sys.platform=='darwin' else 'libpoker_cfr.so')

def build(output=None):
    compiler=shutil.which('clang++') or shutil.which('g++')
    if not compiler:raise RuntimeError('A local clang++ or g++ is required; nothing was installed.')
    output=Path(output) if output else default_library();output.parent.mkdir(parents=True,exist_ok=True)
    command=[compiler,*FLAGS,*(['-dynamiclib'] if sys.platform=='darwin' else ['-shared','-fPIC']),str(SOURCE),'-o',str(output)]
    subprocess.run(command,check=True,capture_output=True,text=True)
    manifest={'source_sha256':sha256(SOURCE.read_bytes()).hexdigest(),'binary_sha256':sha256(output.read_bytes()).hexdigest(),
              'flags':FLAGS,'compiler':subprocess.run([compiler,'--version'],check=True,capture_output=True,text=True).stdout.splitlines()[0],
              'abi':1,'architecture':platform.machine(),'library':str(output.resolve())}
    output.with_suffix(output.suffix+'.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path)
    args=parser.parse_args();print(json.dumps(build(args.output),indent=2))
