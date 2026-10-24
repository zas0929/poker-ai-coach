"""ctypes bridge to our explicitly built numeric kernel. No automatic compilation."""
from array import array
import ctypes as C
from hashlib import sha256
import json
import os
from pathlib import Path
from research.build_native import SOURCE,FLAGS,default_library
from research.compact_utilities import CompactUtilities


def load_library():
    path=Path(os.environ.get('POKER_RESEARCH_NATIVE_LIB',str(default_library())))
    if not path.is_file():raise RuntimeError('Native research kernel is not built; run research/build_native.py explicitly.')
    manifest_path=path.with_suffix(path.suffix+'.json')
    try:manifest=json.loads(manifest_path.read_text())
    except (OSError,ValueError) as error:raise RuntimeError('Native build manifest missing or invalid; rebuild explicitly.') from error
    if manifest.get('abi')!=1 or manifest.get('flags')!=FLAGS or manifest.get('source_sha256')!=sha256(SOURCE.read_bytes()).hexdigest() or manifest.get('binary_sha256')!=sha256(path.read_bytes()).hexdigest():
        raise RuntimeError('Native kernel/manifest is stale or mismatched; rebuild explicitly.')
    library=C.CDLL(str(path.resolve()));library.poker_cfr_abi.restype=C.c_int
    if library.poker_cfr_abi()!=1:raise RuntimeError('Native kernel ABI mismatch.')
    ip=C.POINTER(C.c_int32);dp=C.POINTER(C.c_double)
    library.poker_cfr_train.argtypes=[C.c_int]*7+[ip,ip,ip,ip,ip,dp,dp,ip,ip,dp]
    library.poker_cfr_train.restype=C.c_int
    return library


def train_native(game,iterations):
    if type(iterations) is not int or not 1<=iterations<=2000:raise ValueError('1–2000 iterations required.')
    if not isinstance(game.utilities,CompactUtilities):raise ValueError('Native CFR requires utility_storage="compact" at construction.')
    library=load_library()
    nodes=game.nodes;index={id(node):i for i,node in enumerate(nodes)};keys=sorted(game.keys);info_index={key:i for i,key in enumerate(keys)}
    actors=array('i',(n.actor for n in nodes));edges_at=array('i',[0]);edges=array('i')
    terminal=array('i',(game.utilities.slots.get(id(node),-1) for node in nodes))
    for node in nodes:
        edges.extend(index[id(child)] for child in node.children);edges_at.append(len(edges))
    infos=array('i',(info_index[game.key(node,d)] if node.actor!=-1 else -1 for d in range(len(game.deals)) for node in nodes))
    owners=array('i',(key[0] for key in keys));actions_at=array('i',[0])
    for key in keys:actions_at.append(actions_at[-1]+game.action_counts[key])
    chance=array('d',(d[1] for d in game.deals));output=array('d',[0.])*actions_at[-1]
    if actors.itemsize!=4 or chance.itemsize!=8:raise RuntimeError('Native ABI requires int32 and float64 arrays.')
    def ints(a):return (C.c_int32*len(a)).from_buffer(a)
    def doubles(a):return (C.c_double*len(a)).from_buffer(a)
    code=library.poker_cfr_train(game.n,len(nodes),len(game.deals),len(keys),len(game.utilities.slots),index[id(game.root)],iterations,
        ints(actors),ints(edges_at),ints(edges),ints(infos),ints(terminal),doubles(game.utilities.data),doubles(chance),ints(owners),ints(actions_at),doubles(output))
    if code:raise RuntimeError(f'Native kernel rejected input or allocation (code {code}).')
    return {key:list(output[actions_at[i]:actions_at[i+1]]) for i,key in enumerate(keys)}
