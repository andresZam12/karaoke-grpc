"""Paquete de stubs gRPC generados."""
import sys
from pathlib import Path

# Asegurar que el directorio de stubs generados esté en sys.path para imports internos de protoc
_pkg_dir = str(Path(__file__).resolve().parent)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

try:
    from . import karaoke_pb2 as pb2
    from . import karaoke_pb2_grpc as pb2_grpc
except ImportError:
    import karaoke_pb2 as pb2
    import karaoke_pb2_grpc as pb2_grpc

__all__ = ["pb2", "pb2_grpc"]
