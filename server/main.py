"""Punto de entrada principal para el servidor gRPC de Karaoke."""
import asyncio
import logging
import signal
import sys
from pathlib import Path

import grpc

from generated import pb2_grpc
from server.service import KaraokeService
from server.songs import load_songs_from_dir

DEFAULT_PORT: int = 50051


async def serve(host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
    """Configura y ejecuta el servidor gRPC hasta recibir señal de terminación."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("server")

    songs_dir = Path(__file__).resolve().parent.parent / "songs"
    songs = load_songs_from_dir(songs_dir)
    logger.info(f"Cargadas {len(songs)} canciones desde {songs_dir}")

    server = grpc.aio.server()
    service = KaraokeService(songs)
    pb2_grpc.add_KaraokeServicer_to_server(service, server)

    listen_addr = f"{host}:{port}"
    server.add_insecure_port(listen_addr)
    await server.start()
    logger.info(f"Servidor gRPC iniciado y escuchando en {listen_addr}")

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Señal de detención recibida. Cerrando servidor...")
        stop_event.set()

    # Manejo de señales para apagado limpio (compatible con Unix y Windows)
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)

    try:
        if sys.platform == "win32":
            # En Windows asyncio no siempre soporta loop.add_signal_handler para SIGINT
            await server.wait_for_termination()
        else:
            await stop_event.wait()
            await server.stop(grace=1.0)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Deteniendo servidor gRPC...")
    finally:
        await server.stop(grace=0.5)
        logger.info("Servidor gRPC detenido correctamente.")


def main() -> None:
    """Función de arranque síncrona."""
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
