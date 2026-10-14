"""Implementación del servicio gRPC KaraokeServicer."""
import asyncio
from collections.abc import AsyncIterator
import logging
from typing import Any

import grpc

from generated import pb2, pb2_grpc
from server.room import Room, generate_room_id, server_now_ms
from server.songs import Song

logger = logging.getLogger(__name__)


class KaraokeService(pb2_grpc.KaraokeServicer):
    """Servicio gRPC asíncrono para listar canciones, crear salas, sincronizar y transmitir eventos."""

    def __init__(self, songs: dict[str, Song]) -> None:
        self.songs: dict[str, Song] = songs
        self.rooms: dict[str, Room] = {}

    async def ListSongs(
        self,
        request: pb2.Empty,
        context: grpc.aio.ServicerContext[Any, Any],
    ) -> pb2.SongList:
        """Lista todas las canciones disponibles en el servidor."""
        items = [
            pb2.SongInfo(
                id=song.id,
                title=song.title,
                artist=song.artist,
                line_count=song.line_count,
                duration_s=song.duration_s,
            )
            for song in self.songs.values()
        ]
        return pb2.SongList(songs=items)

    async def CreateRoom(
        self,
        request: pb2.CreateRoomRequest,
        context: grpc.aio.ServicerContext[Any, Any],
    ) -> pb2.Room:
        """Crea una nueva sala con identificador aleatorio de 6 caracteres."""
        song = self.songs.get(request.song_id)
        if not song:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"Canción '{request.song_id}' no encontrada")

        room_id = generate_room_id()
        while room_id in self.rooms:
            room_id = generate_room_id()

        room = Room(room_id=room_id, song=song)
        self.rooms[room_id] = room
        logger.info(f"Sala creada: {room_id} para la canción '{song.id}'")
        return room.to_proto()

    async def Control(
        self,
        request: pb2.ControlRequest,
        context: grpc.aio.ServicerContext[Any, Any],
    ) -> pb2.Room:
        """Controla el estado de reproducción de la sala (play, pause, restart)."""
        room = self.rooms.get(request.room_id)
        if not room:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"Sala '{request.room_id}' no encontrada")

        if request.action == pb2.ControlAction.CONTROL_ACTION_UNSPECIFIED:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Acción de control no especificada")

        room.handle_control(request.action)
        return room.to_proto()

    async def Join(
        self,
        request: pb2.JoinRequest,
        context: grpc.aio.ServicerContext[Any, Any],
    ) -> AsyncIterator[pb2.SongEvent]:
        """Streaming de eventos de la sala para un cliente conectado."""
        room = self.rooms.get(request.room_id)
        if not room:
            await context.abort(grpc.StatusCode.NOT_FOUND, f"Sala '{request.room_id}' no encontrada")

        client_name = request.client_name or "Anon"
        logger.info(f"Cliente '{client_name}' ingresó a la sala {request.room_id}")

        queue = room.subscribe()
        try:
            # Emitir estado actual inmediatamente al unirse
            initial_state = pb2.SongEvent(
                type=pb2.EventType.EVENT_STATE_CHANGE,
                play_at_server_ms=server_now_ms(),
                song_time_s=room.get_current_position_s(),
                state=room.state,
            )
            await queue.put(initial_state)

            # Si la sala ya está reproduciendo, enviar también la línea actual
            if room.state == pb2.RoomState.ROOM_PLAYING:
                current_line = room.get_current_line_event()
                if current_line:
                    await queue.put(current_line)

            while True:
                event = await queue.get()
                yield event
        except asyncio.CancelledError:
            pass
        finally:
            room.unsubscribe(queue)
            logger.info(f"Cliente '{client_name}' abandonó la sala {request.room_id}")

    async def Sync(
        self,
        request_iterator: AsyncIterator[pb2.ClockPing],
        context: grpc.aio.ServicerContext[Any, Any],
    ) -> AsyncIterator[pb2.ClockPong]:
        """Responde a pings de sincronización de reloj con la hora actual del servidor."""
        async for ping in request_iterator:
            yield pb2.ClockPong(
                client_send_ms=ping.client_send_ms,
                server_ms=server_now_ms(),
            )
