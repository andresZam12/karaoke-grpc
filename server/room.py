"""Implementación de la clase Room: estado, scheduler de reproducción y suscriptores."""
import asyncio
import logging
import random
import string
import time
from typing import Any

from generated import pb2
from server.songs import Song

logger = logging.getLogger(__name__)

LEAD_MS: int = 700


def server_now_ms() -> int:
    """Devuelve el tiempo actual del servidor en milisegundos de época."""
    return time.time_ns() // 1_000_000


def generate_room_id() -> str:
    """Genera un identificador de sala de 6 caracteres alfanuméricos en mayúscula."""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=6))


class Room:
    """Gestiona el ciclo de vida, la cola de eventos y la sincronización temporal de una sala."""

    def __init__(self, room_id: str, song: Song) -> None:
        self.room_id: str = room_id
        self.song: Song = song
        self.state: pb2.RoomState = pb2.RoomState.ROOM_WAITING
        self.position_s: float = 0.0
        self.start_ms: int = 0
        self.subscribers: set[asyncio.Queue[pb2.SongEvent]] = set()
        self.scheduler_task: asyncio.Task[Any] | None = None

    def get_current_position_s(self) -> float:
        """Calcula la posición actual en segundos según el estado de reproducción."""
        if self.state == pb2.RoomState.ROOM_PLAYING:
            now = server_now_ms()
            elapsed_s = (now - self.start_ms) / 1000.0
            return max(0.0, min(round(elapsed_s, 2), self.song.duration_s))
        return self.position_s

    def to_proto(self) -> pb2.Room:
        """Serializa la sala al mensaje protobuf Room."""
        return pb2.Room(
            room_id=self.room_id,
            song_id=self.song.id,
            state=self.state,
            position_s=self.get_current_position_s(),
        )

    def subscribe(self) -> asyncio.Queue[pb2.SongEvent]:
        """Registra un nuevo cliente y devuelve su cola de eventos."""
        queue: asyncio.Queue[pb2.SongEvent] = asyncio.Queue()
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[pb2.SongEvent]) -> None:
        """Elimina la cola de un cliente de los suscriptores."""
        self.subscribers.discard(queue)

    def broadcast(self, event: pb2.SongEvent) -> None:
        """Emite un evento a todos los clientes suscritos."""
        for queue in list(self.subscribers):
            queue.put_nowait(event)

    def get_current_line_event(self) -> pb2.SongEvent | None:
        """Devuelve el evento de la línea actual para clientes que ingresan tarde o reanudan."""
        if self.state != pb2.RoomState.ROOM_PLAYING:
            return None

        curr_pos = self.get_current_position_s()
        curr_idx = -1
        for idx, line in enumerate(self.song.lines):
            if line.t <= curr_pos:
                curr_idx = idx
            else:
                break

        if curr_idx < 0:
            return None

        line = self.song.lines[curr_idx]
        has_next = (curr_idx + 1) < len(self.song.lines)
        next_line = self.song.lines[curr_idx + 1] if has_next else None

        return pb2.SongEvent(
            type=pb2.EventType.EVENT_LINE,
            play_at_server_ms=server_now_ms() + LEAD_MS,
            song_time_s=line.t,
            chord=line.chord,
            lyric=line.lyric,
            line_index=curr_idx,
            next_chord=next_line.chord if next_line else "",
            next_lyric=next_line.lyric if next_line else "",
            state=self.state,
        )

    def handle_control(self, action: pb2.ControlAction) -> None:
        """Aplica una acción de control (play, pause, restart) según el protocolo."""
        if action == pb2.ControlAction.ACTION_PLAY:
            self._handle_play()
        elif action == pb2.ControlAction.ACTION_PAUSE:
            self._handle_pause()
        elif action == pb2.ControlAction.ACTION_RESTART:
            self._handle_restart()

    def _cancel_scheduler(self) -> None:
        if self.scheduler_task and not self.scheduler_task.done():
            self.scheduler_task.cancel()
            self.scheduler_task = None

    def _handle_play(self) -> None:
        if self.state == pb2.RoomState.ROOM_PLAYING:
            return

        was_paused = (self.state == pb2.RoomState.ROOM_PAUSED)
        if self.state == pb2.RoomState.ROOM_FINISHED:
            self.position_s = 0.0

        now = server_now_ms()
        self.start_ms = now + LEAD_MS - int(self.position_s * 1000)
        self.state = pb2.RoomState.ROOM_PLAYING

        logger.info(f"Sala {self.room_id}: PLAY en position_s={self.position_s}")

        # Notificar cambio de estado a todos
        state_event = pb2.SongEvent(
            type=pb2.EventType.EVENT_STATE_CHANGE,
            play_at_server_ms=now,
            song_time_s=self.position_s,
            state=self.state,
        )
        self.broadcast(state_event)

        # Iniciar scheduler asíncrono
        self._cancel_scheduler()
        self.scheduler_task = asyncio.create_task(self._run_scheduler(was_paused))

    def _handle_pause(self) -> None:
        if self.state != pb2.RoomState.ROOM_PLAYING:
            return

        now = server_now_ms()
        self._cancel_scheduler()
        self.position_s = self.get_current_position_s()
        self.state = pb2.RoomState.ROOM_PAUSED

        logger.info(f"Sala {self.room_id}: PAUSE en position_s={self.position_s}")

        state_event = pb2.SongEvent(
            type=pb2.EventType.EVENT_STATE_CHANGE,
            play_at_server_ms=now,
            song_time_s=self.position_s,
            state=self.state,
        )
        self.broadcast(state_event)

    def _handle_restart(self) -> None:
        now = server_now_ms()
        self._cancel_scheduler()
        self.position_s = 0.0
        self.state = pb2.RoomState.ROOM_WAITING

        logger.info(f"Sala {self.room_id}: RESTART")

        state_event = pb2.SongEvent(
            type=pb2.EventType.EVENT_STATE_CHANGE,
            play_at_server_ms=now,
            song_time_s=0.0,
            state=self.state,
        )
        self.broadcast(state_event)

    async def _run_scheduler(self, was_paused: bool) -> None:
        """Planificador que duerme hasta (play_at - LEAD_MS) y emite cada línea."""
        try:
            if was_paused:
                # Al reanudar tras pausa, emitir primero la línea actual con play_at = ahora + LEAD_MS
                current_event = self.get_current_line_event()
                if current_event:
                    self.broadcast(current_event)
                indices = [i for i, line in enumerate(self.song.lines) if line.t > self.position_s]
            else:
                indices = [i for i, line in enumerate(self.song.lines) if line.t >= self.position_s]

            for idx in indices:
                line = self.song.lines[idx]
                play_at = self.start_ms + int(line.t * 1000)
                wake_at = play_at - LEAD_MS
                delay_ms = wake_at - server_now_ms()
                if delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000.0)

                has_next = (idx + 1) < len(self.song.lines)
                next_line = self.song.lines[idx + 1] if has_next else None

                event = pb2.SongEvent(
                    type=pb2.EventType.EVENT_LINE,
                    play_at_server_ms=play_at,
                    song_time_s=line.t,
                    chord=line.chord,
                    lyric=line.lyric,
                    line_index=idx,
                    next_chord=next_line.chord if next_line else "",
                    next_lyric=next_line.lyric if next_line else "",
                    state=self.state,
                )
                self.broadcast(event)

            # Espera 3 segundos tras la última línea y finaliza la canción
            await asyncio.sleep(3.0)
            self.state = pb2.RoomState.ROOM_FINISHED
            self.position_s = self.song.duration_s

            logger.info(f"Sala {self.room_id}: Canción finalizada (FINISHED)")

            end_event = pb2.SongEvent(
                type=pb2.EventType.EVENT_END,
                play_at_server_ms=server_now_ms(),
                song_time_s=self.position_s,
                state=self.state,
            )
            self.broadcast(end_event)

        except asyncio.CancelledError:
            # Planificador cancelado intencionalmente por pausa o reinicio
            pass
        except Exception as exc:
            logger.error(f"Error inesperado en scheduler de sala {self.room_id}: {exc}", exc_info=True)
