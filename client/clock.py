"""Módulo de sincronización de reloj cliente-servidor (ClockSync)."""
import asyncio
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
import logging
import time
from typing import Any

from generated import pb2, pb2_grpc

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClockSample:
    """Muestra individual de sincronización con RTT y offset calculados."""
    rtt: float
    offset: float
    timestamp_ms: int


class ClockSync:
    """Sincronizador de reloj usando el RPC bidireccional Sync y filtro de menor RTT."""

    def __init__(self, stub: pb2_grpc.KaraokeStub, fake_skew_ms: int = 0) -> None:
        self.stub: pb2_grpc.KaraokeStub = stub
        self.fake_skew_ms: int = fake_skew_ms
        self.samples: deque[ClockSample] = deque(maxlen=8)
        self.current_offset: float = 0.0
        self.current_rtt: float = 0.0
        self.is_synced: asyncio.Event = asyncio.Event()

        self._ping_queue: asyncio.Queue[pb2.ClockPing | None] = asyncio.Queue()
        self._sync_task: asyncio.Task[Any] | None = None
        self._send_task: asyncio.Task[Any] | None = None
        self._receive_task: asyncio.Task[Any] | None = None
        self._response_stream: Any = None
        self._running: bool = False

    def local_now_ms(self) -> int:
        """Devuelve la hora local del cliente en ms, aplicando el desfase artificial fake_skew_ms."""
        real_ms = time.time_ns() // 1_000_000
        return real_ms + self.fake_skew_ms

    def server_now_ms(self) -> int:
        """Devuelve la hora estimada del servidor aplicando el offset actual."""
        return int(round(self.local_now_ms() + self.current_offset))

    async def start(self) -> None:
        """Inicia las tareas asíncronas de envío y recepción de pings."""
        if self._running:
            return
        self._running = True
        self._sync_task = asyncio.create_task(self._run_sync())

    async def stop(self) -> None:
        """Detiene la sincronización y limpia las tareas pendientes."""
        self._running = False
        await self._ping_queue.put(None)
        if self._response_stream is not None:
            self._response_stream.cancel()
        if self._send_task and not self._send_task.done():
            self._send_task.cancel()
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass

    async def wait_until_synced(self, timeout: float = 5.0) -> None:
        """Espera a que se reciba al menos un pong para tener un offset inicial válido."""
        await asyncio.wait_for(self.is_synced.wait(), timeout=timeout)

    async def _ping_generator(self) -> AsyncIterator[pb2.ClockPing]:
        """Generador asíncrono para enviar pings en el stream bidireccional."""
        while self._running:
            item = await self._ping_queue.get()
            if item is None:
                break
            yield item

    async def _send_loop(self) -> None:
        """Envía 8 pings iniciales separados por 200 ms, y luego un ping cada 5 segundos."""
        try:
            # 8 pings iniciales para convergencia rápida
            for _ in range(8):
                if not self._running:
                    return
                ping = pb2.ClockPing(client_send_ms=self.local_now_ms())
                await self._ping_queue.put(ping)
                await asyncio.sleep(0.2)

            # Pings periódicos de mantenimiento
            while self._running:
                await asyncio.sleep(5.0)
                if not self._running:
                    return
                ping = pb2.ClockPing(client_send_ms=self.local_now_ms())
                await self._ping_queue.put(ping)
        except asyncio.CancelledError:
            pass

    async def _receive_loop(self, response_stream: Any) -> None:
        """Procesa pongs entrantes, calcula offset y actualiza la mejor muestra (menor RTT)."""
        try:
            async for pong in response_stream:
                t1 = self.local_now_ms()
                rtt = float(t1 - pong.client_send_ms)
                offset = float(pong.server_ms + (rtt / 2.0) - t1)

                sample = ClockSample(rtt=rtt, offset=offset, timestamp_ms=t1)
                self.samples.append(sample)

                # Usar como offset la muestra con menor RTT de las últimas 8
                best_sample = min(self.samples, key=lambda s: s.rtt)
                self.current_offset = best_sample.offset
                self.current_rtt = best_sample.rtt

                if not self.is_synced.is_set():
                    self.is_synced.set()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if self._running:
                logger.debug(f"Stream de sync finalizado: {exc}")

    async def _run_sync(self) -> None:
        """Ejecuta en paralelo el envío y la recepción del stream bidireccional."""
        try:
            self._response_stream = self.stub.Sync(self._ping_generator())
            self._send_task = asyncio.create_task(self._send_loop())
            self._receive_task = asyncio.create_task(self._receive_loop(self._response_stream))

            await asyncio.gather(self._send_task, self._receive_task)
        except asyncio.CancelledError:
            if self._send_task and not self._send_task.done():
                self._send_task.cancel()
            if self._receive_task and not self._receive_task.done():
                self._receive_task.cancel()
        except Exception as exc:
            if self._running:
                logger.error(f"Error en sesión Sync: {exc}")
        finally:
            if self._response_stream is not None:
                self._response_stream.cancel()
