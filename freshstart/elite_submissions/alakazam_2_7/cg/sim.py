import ctypes
import os

class StartData(ctypes.Structure):
    _fields_ = [
        ("battlePtr", ctypes.c_void_p),
        ("errorPlayer", ctypes.c_int),
        ("errorType", ctypes.c_int),
    ]

class SerialData(ctypes.Structure):
    _fields_ = [
        ("json", ctypes.c_char_p),
        ("data", ctypes.POINTER(ctypes.c_ubyte)),
        ("count", ctypes.c_int),
        ("selectPlayer", ctypes.c_int)
    ]

if os.environ.get("CG_LIB"):  # local eval override (native mac build); unset on Kaggle
    lib_path = os.environ["CG_LIB"]
elif os.name == 'nt':
    lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cg.dll")
else:
    lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libcg.so")
lib = ctypes.cdll.LoadLibrary(lib_path)

lib.GameInitialize()

lib.BattleStart.restype = StartData
lib.BattleStart.argtypes = [ctypes.POINTER(ctypes.c_int)]

# Newer local builds expose deterministic evaluation.  Keep this optional so
# the unchanged competition library remains a supported runtime dependency.
HAS_SEEDED_BATTLE = hasattr(lib, "BattleStartSeeded")
if HAS_SEEDED_BATTLE:
    lib.BattleStartSeeded.restype = StartData
    lib.BattleStartSeeded.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint]

lib.AgentStart.restype = ctypes.c_void_p

HAS_SEEDED_AGENT = hasattr(lib, "AgentStartSeeded")
if HAS_SEEDED_AGENT:
    lib.AgentStartSeeded.restype = ctypes.c_void_p
    lib.AgentStartSeeded.argtypes = [ctypes.c_uint]

lib.BattleFinish.argtypes = [ctypes.c_void_p]

lib.GetBattleData.restype = SerialData
lib.GetBattleData.argtypes = [ctypes.c_void_p]

lib.Select.restype = ctypes.c_int
lib.Select.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.c_int]

lib.VisualizeData.restype = ctypes.c_char_p
lib.VisualizeData.argtypes = [ctypes.c_void_p]

lib.SearchBegin.restype = ctypes.c_char_p
lib.SearchBegin.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.c_int]

lib.SearchStep.restype = ctypes.c_char_p
lib.SearchStep.argtypes = [ctypes.c_void_p, ctypes.c_int64, ctypes.POINTER(ctypes.c_int), ctypes.c_int]

lib.SearchEnd.argtypes = [ctypes.c_void_p]

lib.SearchRelease.argtypes = [ctypes.c_void_p, ctypes.c_int64]

lib.AllCard.restype = ctypes.c_char_p

lib.AllAttack.restype = ctypes.c_char_p

class Battle:
    battle_ptr = None
    obs = None
