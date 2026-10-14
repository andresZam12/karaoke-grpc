"""CLI del cliente de Karaoke con argparse y subcomandos (list, create, join, control)."""
import argparse
import asyncio
import sys
from typing import NoReturn

import grpc
from rich.console import Console

from client.clock import ClockSync
from client.display import (
    render_end,
    render_karaoke_line,
    render_room_created,
    render_songs_table,
    render_state_change,
)
from generated import pb2, pb2_grpc

console = Console()

ACTION_MAP = {
    "play": pb2.ControlAction.ACTION_PLAY,
    "pause": pb2.ControlAction.ACTION_PAUSE,
    "restart": pb2.ControlAction.ACTION_RESTART,
}


async def cmd_list(stub: pb2_grpc.KaraokeStub) -> None:
    """Solicita y muestra la lista de canciones disponibles."""
    response = await stub.ListSongs(pb2.Empty())
    render_songs_table(response)


async def cmd_create(stub: pb2_grpc.KaraokeStub, song_id: str) -> None:
    """Crea una nueva sala de karaoke e imprime su identificador."""
    request = pb2.CreateRoomRequest(song_id=song_id)
    room = await stub.CreateRoom(request)
    render_room_created(room)


async def cmd_control(stub: pb2_grpc.KaraokeStub, room_id: str, action_str: str) -> None:
    """Envía una orden de control de reproducción a la sala."""
    action_enum = ACTION_MAP.get(action_str.lower())
    if not action_enum:
        console.print(f"[bold red]Acción inválida:[/bold red] {action_str}. Opciones: play, pause, restart")
        return

    request = pb2.ControlRequest(room_id=room_id, action=action_enum)
    room = await stub.Control(request)
    console.print(
        f"[green]Control ejecutado:[/green] Sala [bold cyan]{room.room_id}[/bold cyan] -> "
        f"Estado: [bold yellow]{pb2.RoomState.Name(room.state)}[/bold yellow], "
        f"Posición: [bold]{room.position_s:.1f}s[/bold]"
    )


async def cmd_join(
    stub: pb2_grpc.KaraokeStub,
    room_id: str,
    name: str,
    fake_skew_ms: int,
) -> None:
    """Se conecta a una sala, sincroniza el reloj y muestra la letra y acordes en tiempo real."""
    clock = ClockSync(stub=stub, fake_skew_ms=fake_skew_ms)
    await clock.start()

    with console.status("[cyan]Sincronizando reloj con el servidor...[/cyan]", spinner="dots"):
        try:
            await clock.wait_until_synced(timeout=3.0)
        except asyncio.TimeoutError:
            console.print("[yellow]Aviso: No se pudo sincronizar en 3s, continuando con hora local...[/yellow]")

    console.print(
        f"[green]✓ Conectado.[/green] Sala: [bold cyan]{room_id}[/bold cyan] | "
        f"Cliente: [bold white]{name}[/bold white] | "
        f"Offset reloj: [bold green]{clock.current_offset:+.1f} ms[/bold green]\n"
    )

    request = pb2.JoinRequest(room_id=room_id, client_name=name)
    stream = stub.Join(request)

    try:
        async for event in stream:
            if event.type == pb2.EventType.EVENT_STATE_CHANGE:
                render_state_change(event.state, room_id, name, clock)

            elif event.type == pb2.EventType.EVENT_LINE:
                # Sincronización precisa: esperar hasta que la hora estimada alcance play_at_server_ms
                wait_ms = event.play_at_server_ms - clock.server_now_ms()
                if wait_ms > 0:
                    await asyncio.sleep(wait_ms / 1000.0)

                render_karaoke_line(
                    chord=event.chord,
                    lyric=event.lyric,
                    next_chord=event.next_chord,
                    next_lyric=event.next_lyric,
                    room_id=room_id,
                    client_name=name,
                    line_index=event.line_index,
                    clock=clock,
                )

            elif event.type == pb2.EventType.EVENT_END:
                render_end(room_id)
                break

    except asyncio.CancelledError:
        pass
    finally:
        await clock.stop()
        stream.cancel()


def parse_args() -> argparse.Namespace:
    """Configura las opciones de la línea de comandos."""
    parser = argparse.ArgumentParser(description="Cliente CLI para karaoke-grpc")
    parser.add_argument(
        "--server",
        default="localhost:50051",
        help="Dirección host:puerto del servidor gRPC (por defecto: localhost:50051)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcomando: list
    subparsers.add_parser("list", help="Listar canciones disponibles")

    # Subcomando: create
    create_parser = subparsers.add_parser("create", help="Crear una nueva sala")
    create_parser.add_argument("--song", required=True, help="ID de la canción (ej: estrellita, campanero)")

    # Subcomando: join
    join_parser = subparsers.add_parser("join", help="Unirse a una sala y ver karaoke")
    join_parser.add_argument("--room", required=True, help="ID de la sala (6 caracteres)")
    join_parser.add_argument("--name", default="Vocalista", help="Nombre del cliente")
    join_parser.add_argument(
        "--fake-skew-ms",
        type=int,
        default=0,
        help="Desfase simulado del reloj local en ms (para pruebas de sincronización)",
    )

    # Subcomando: control
    ctrl_parser = subparsers.add_parser("control", help="Controlar reproducción (modo director)")
    ctrl_parser.add_argument("--room", required=True, help="ID de la sala")
    ctrl_parser.add_argument(
        "--action",
        required=True,
        choices=["play", "pause", "restart"],
        help="Acción a ejecutar: play, pause, restart",
    )

    return parser.parse_args()


async def async_main() -> None:
    """Función principal asíncrona que gestiona canales y llamadas gRPC con manejo de errores."""
    args = parse_args()
    channel = grpc.aio.insecure_channel(args.server)
    stub = pb2_grpc.KaraokeStub(channel)

    try:
        if args.command == "list":
            await cmd_list(stub)
        elif args.command == "create":
            await cmd_create(stub, args.song)
        elif args.command == "control":
            await cmd_control(stub, args.room, args.action)
        elif args.command == "join":
            await cmd_join(stub, args.room, args.name, args.fake_skew_ms)
    except grpc.aio.AioRpcError as err:
        if err.code() == grpc.StatusCode.NOT_FOUND:
            console.print(f"[bold red]Error:[/bold red] {err.details()}")
        elif err.code() == grpc.StatusCode.UNAVAILABLE:
            console.print(
                f"[bold red]Error de conexión:[/bold red] No se pudo conectar al servidor en [bold cyan]{args.server}[/bold cyan]. "
                "Verifica que el servidor esté en ejecución."
            )
        elif err.code() == grpc.StatusCode.INVALID_ARGUMENT:
            console.print(f"[bold red]Argumento inválido:[/bold red] {err.details()}")
        else:
            console.print(f"[bold red]Error gRPC [{err.code().name}]:[/bold red] {err.details()}")
    finally:
        await channel.close()


def main() -> None:
    """Punto de entrada síncrono que captura KeyboardInterrupt limpiamente."""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        console.print("\n[dim]Sesión finalizada por el usuario (Ctrl+C).[/dim]")
        sys.exit(0)


if __name__ == "__main__":
    main()
