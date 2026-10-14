"""Pruebas unitarias y de integración para karaoke-grpc."""
import asyncio
import grpc
import pytest
import pytest_asyncio

from generated import pb2, pb2_grpc
from server.service import KaraokeService
from server.songs import Song, SongLine, load_songs_from_dir, validate_and_parse_song


def test_song_validation():
    """Verifica que canciones con tiempos 't' no estrictamente crecientes sean rechazadas con ValueError."""
    invalid_data = {
        "id": "bad_song",
        "title": "Cancion Invalida",
        "artist": "Anonimo",
        "lines": [
            {"t": 0.0, "chord": "C", "lyric": "Linea 1"},
            {"t": 2.5, "chord": "F", "lyric": "Linea 2"},
            {"t": 2.0, "chord": "G", "lyric": "Linea 3 (retroceso en t)"},
        ],
    }

    with pytest.raises(ValueError, match="no son estrictamente crecientes"):
        validate_and_parse_song(invalid_data)

    equal_t_data = {
        "id": "equal_t_song",
        "title": "Cancion con tiempos repetidos",
        "artist": "Anonimo",
        "lines": [
            {"t": 1.0, "chord": "C", "lyric": "Linea 1"},
            {"t": 1.0, "chord": "G", "lyric": "Linea 2 con mismo t"},
        ],
    }

    with pytest.raises(ValueError, match="no son estrictamente crecientes"):
        validate_and_parse_song(equal_t_data)


def test_load_default_songs():
    """Verifica que las canciones por defecto en songs/ carguen correctamente."""
    songs = load_songs_from_dir("songs")
    assert "estrellita" in songs
    assert "campanero" in songs
    assert len(songs["estrellita"].lines) >= 8
    assert len(songs["campanero"].lines) >= 8


@pytest_asyncio.fixture
async def test_env():
    """Levanta un servidor gRPC real en puerto efímero con una canción de prueba corta."""
    test_song = Song(
        id="short_test",
        title="Prueba Corta",
        artist="Test Artist",
        lines=[
            SongLine(t=0.0, chord="C", lyric="Línea 0"),
            SongLine(t=1.0, chord="F", lyric="Línea 1"),
            SongLine(t=2.0, chord="G", lyric="Línea 2"),
        ],
    )
    server = grpc.aio.server()
    service = KaraokeService({"short_test": test_song})
    pb2_grpc.add_KaraokeServicer_to_server(service, server)

    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()

    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    stub = pb2_grpc.KaraokeStub(channel)

    try:
        yield {
            "server": server,
            "service": service,
            "channel": channel,
            "stub": stub,
            "song": test_song,
            "port": port,
        }
    finally:
        await channel.close()
        await server.stop(grace=0)


@pytest.mark.asyncio
async def test_room_lifecycle(test_env):
    """Crea una sala, ejecuta play, pause, restart y verifica estados y position_s."""
    stub = test_env["stub"]

    # 1. Crear sala
    created = await stub.CreateRoom(pb2.CreateRoomRequest(song_id="short_test"))
    assert created.room_id
    assert created.state == pb2.RoomState.ROOM_WAITING
    assert created.position_s == 0.0

    # 2. Play
    played = await stub.Control(
        pb2.ControlRequest(room_id=created.room_id, action=pb2.ControlAction.ACTION_PLAY)
    )
    assert played.state == pb2.RoomState.ROOM_PLAYING

    # Esperar avance superando LEAD_MS (700 ms)
    await asyncio.sleep(1.0)

    # 3. Pause
    paused = await stub.Control(
        pb2.ControlRequest(room_id=created.room_id, action=pb2.ControlAction.ACTION_PAUSE)
    )
    assert paused.state == pb2.RoomState.ROOM_PAUSED
    assert paused.position_s > 0.0

    # 4. Restart
    restarted = await stub.Control(
        pb2.ControlRequest(room_id=created.room_id, action=pb2.ControlAction.ACTION_RESTART)
    )
    assert restarted.state == pb2.RoomState.ROOM_WAITING
    assert restarted.position_s == 0.0


@pytest.mark.asyncio
async def test_join_unknown_room(test_env):
    """Join con sala inexistente devuelve NOT_FOUND."""
    stub = test_env["stub"]

    stream = stub.Join(pb2.JoinRequest(room_id="NOEXIS", client_name="Tester"))
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await stream.read()

    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_late_joiner(test_env):
    """Un cliente que se une a mitad de canción recibe el estado PLAYING y la línea actual."""
    stub = test_env["stub"]

    room = await stub.CreateRoom(pb2.CreateRoomRequest(song_id="short_test"))
    await stub.Control(pb2.ControlRequest(room_id=room.room_id, action=pb2.ControlAction.ACTION_PLAY))

    # Esperar a que la canción avance pasando la línea 1 (t=1.0 s)
    # Con LEAD_MS (0.7s), la línea 1 ocurre a 0.7 + 1.0 = 1.7s tras el PLAY
    await asyncio.sleep(1.9)

    stream = stub.Join(pb2.JoinRequest(room_id=room.room_id, client_name="LateUser"))

    # Primer evento: cambio de estado con ROOM_PLAYING
    event1 = await stream.read()
    assert event1.type == pb2.EventType.EVENT_STATE_CHANGE
    assert event1.state == pb2.RoomState.ROOM_PLAYING

    # Segundo evento: línea actual activa
    event2 = await stream.read()
    assert event2.type == pb2.EventType.EVENT_LINE
    assert event2.line_index == 1
    assert event2.chord == "F"
    assert event2.lyric == "Línea 1"

    # Cancelar lectura limpia
    stream.cancel()
