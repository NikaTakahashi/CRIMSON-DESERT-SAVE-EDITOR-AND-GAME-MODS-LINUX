try:
    from dmm_parser import *
    import dmm_parser as _dmm
    if not hasattr(_dmm, 'extract_file'):
        raise ImportError("dmm_parser missing native functions")
except ImportError as e:
    print(f"Error: {e}")
    try:
        from crimson_rs.crimson_rs import *
    except ModuleNotFoundError:
        # Native bindings are not built for this platform: crimson_rs.pyd is a
        # Windows extension module. Pure-Python tooling (enums, legacy) still works.
        pass
from crimson_rs.enums import Compression, Crypto, Language
