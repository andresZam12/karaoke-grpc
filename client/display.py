"""Módulo de interfaz y renderizado en terminal usando la biblioteca rich."""
from typing import Any

from rich.align import Align
from rich.box import ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from generated import pb2

console = Console()

STATE_LABELS: dict[int, tuple[str, str]] = {
    pb2.RoomState.ROOM_WAITING: ("EN ESPERA", "yellow"),
    pb2.RoomState.ROOM_PLAYING: ("REPRODUCIENDO", "green"),
    pb2.RoomState.ROOM_PAUSED: ("PAUSADA", "magenta"),
    pb2.RoomState.ROOM_FINISHED: ("FINALIZADA", "blue"),
}


def render_songs_table(song_list: pb2.SongList) -> None:
    """Imprime una tabla elegante con las canciones disponibles."""
    table = Table(title="🎶 Canciones Disponibles en Karaoke-gRPC 🎶", box=ROUNDED)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Título", style="bold white")
    table.add_column("Artista", style="italic yellow")
    table.add_column("Líneas", justify="right", style="green")
    table.add_column("Duración", justify="right", style="magenta")

    for s in song_list.songs:
        table.add_row(
            s.id,
            s.title,
            s.artist,
            str(s.line_count),
            f"{s.duration_s:.1f} s",
        )

    console.print()
    console.print(table)
    console.print()


def render_room_created(room: pb2.Room) -> None:
    """Imprime el mensaje de confirmación tras crear una sala."""
    text = Text()
    text.append("Sala creada exitosamente:\n\n", style="green")
    text.append(f"  ID de Sala: {room.room_id}\n", style="bold cyan")
    text.append(f"  Canción:    {room.song_id}\n\n", style="white")
    text.append("Para unirte ejecuta:\n", style="dim")
    text.append(f"  python -m client.main join --room {room.room_id} --name TuNombre\n", style="bold yellow")
    text.append("Para iniciar la reproducción ejecuta:\n", style="dim")
    text.append(f"  python -m client.main control --room {room.room_id} --action play\n", style="bold yellow")

    panel = Panel(text, title="[bold]Sala Lista[/bold]", border_style="cyan", box=ROUNDED)
    console.print(panel)


def render_state_change(state: int, room_id: str, client_name: str, clock: Any) -> None:
    """Muestra un panel informativo al cambiar de estado la sala."""
    state_str, state_color = STATE_LABELS.get(state, ("DESCONOCIDO", "white"))

    status_line = (
        f"Sala: [bold cyan]{room_id}[/bold cyan] | "
        f"Cliente: [bold white]{client_name}[/bold white] | "
        f"Offset: [bold green]{clock.current_offset:+.1f} ms[/bold green] | "
        f"RTT: [bold yellow]{clock.current_rtt:.1f} ms[/bold yellow] | "
        f"Fake Skew: [bold magenta]{clock.fake_skew_ms:+d} ms[/bold magenta]"
    )

    body = Text()
    body.append(f"\nEstado de la sala: ", style="bold")
    body.append(f"{state_str}\n\n", style=f"bold {state_color}")

    panel = Panel(
        Align.center(body),
        title=f"[bold]Karaoke gRPC[/bold]",
        subtitle=status_line,
        border_style=state_color,
        box=ROUNDED,
    )
    console.print(panel)


def render_karaoke_line(
    chord: str,
    lyric: str,
    next_chord: str,
    next_lyric: str,
    room_id: str,
    client_name: str,
    line_index: int,
    clock: Any,
) -> None:
    """Renderiza la línea actual de karaoke: acorde grande, letra destacada y siguiente línea."""
    chord_display = f"♫  [bold red on yellow]  {chord or '---'}  [/bold red on yellow]  ♫"

    content = Text()
    content.append("\n")
    content.append(f"{lyric}\n\n", style="bold white")

    if next_lyric:
        next_chord_str = f"[{next_chord}] " if next_chord else ""
        content.append(f"Siguiente: {next_chord_str}{next_lyric}\n", style="dim italic")
    else:
        content.append("--- Fin de la canción ---\n", style="dim italic")

    status_line = (
        f"Línea #{line_index + 1} | "
        f"Sala: [bold cyan]{room_id}[/bold cyan] | "
        f"Offset: [bold green]{clock.current_offset:+.1f} ms[/bold green] | "
        f"RTT: [bold yellow]{clock.current_rtt:.1f} ms[/bold yellow] | "
        f"Skew: [bold magenta]{clock.fake_skew_ms:+d} ms[/bold magenta]"
    )

    full_panel = Panel(
        Align.center(
            Panel(
                Align.center(Text.from_markup(chord_display)),
                box=ROUNDED,
                border_style="yellow",
                expand=False,
            )
        )
        + Align.center(content),
        title="[bold green]● REPRODUCIENDO EN VIVO[/bold green]",
        subtitle=status_line,
        border_style="bright_blue",
        box=ROUNDED,
    )

    console.print(full_panel)


def render_end(room_id: str) -> None:
    """Renderiza el fin de la canción."""
    text = Text("\n🎉 ¡Canción terminada! Gracias por cantar. 🎉\n", style="bold green")
    panel = Panel(Align.center(text), title="[bold]Fin del Karaoke[/bold]", border_style="green", box=ROUNDED)
    console.print(panel)
