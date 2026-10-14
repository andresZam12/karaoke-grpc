"""Módulo para carga y validación de canciones en formato JSON."""
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SongLine:
    """Representa una línea lírica asociada a un acorde y un instante de tiempo."""
    t: float
    chord: str
    lyric: str


@dataclass(frozen=True)
class Song:
    """Representa una canción completa con metadatos y secuencia de líneas."""
    id: str
    title: str
    artist: str
    lines: list[SongLine]

    @property
    def line_count(self) -> int:
        return len(self.lines)

    @property
    def duration_s(self) -> float:
        if not self.lines:
            return 0.0
        # La duración estimada contempla la última línea más un tiempo de lectura
        return round(self.lines[-1].t + 3.0, 2)


def validate_and_parse_song(data: dict[str, Any]) -> Song:
    """Valida los campos requeridos y que los tiempos 't' sean estrictamente crecientes."""
    required_keys = {"id", "title", "artist", "lines"}
    missing = required_keys - set(data.keys())
    if missing:
        raise ValueError(f"Faltan campos requeridos en la canción: {', '.join(sorted(missing))}")

    song_id = str(data["id"]).strip()
    title = str(data["title"]).strip()
    artist = str(data["artist"]).strip()
    lines_raw = data.get("lines")

    if not isinstance(lines_raw, list) or len(lines_raw) == 0:
        raise ValueError(f"La canción '{song_id}' debe contener una lista no vacía de 'lines'")

    parsed_lines: list[SongLine] = []
    prev_t: float | None = None

    for idx, item in enumerate(lines_raw):
        if not isinstance(item, dict):
            raise ValueError(f"La línea {idx} de la canción '{song_id}' no es un diccionario válido")

        if "t" not in item or "chord" not in item or "lyric" not in item:
            raise ValueError(f"La línea {idx} de la canción '{song_id}' debe contener 't', 'chord' y 'lyric'")

        try:
            t = float(item["t"])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Tiempo inválido en la línea {idx} de la canción '{song_id}': {item['t']}") from exc

        if t < 0:
            raise ValueError(f"El tiempo 't' no puede ser negativo en la línea {idx} de '{song_id}': {t}")

        if prev_t is not None and t <= prev_t:
            raise ValueError(
                f"Tiempos 't' no son estrictamente crecientes en la canción '{song_id}': "
                f"línea {idx} (t={t}) <= línea previa (t={prev_t})"
            )

        chord = str(item["chord"]).strip()
        lyric = str(item["lyric"])
        parsed_lines.append(SongLine(t=t, chord=chord, lyric=lyric))
        prev_t = t

    return Song(id=song_id, title=title, artist=artist, lines=parsed_lines)


def load_song_from_file(path: str | Path) -> Song:
    """Carga y valida una canción desde una ruta de archivo JSON."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Archivo de canción no encontrado: {file_path}")

    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    return validate_and_parse_song(data)


def load_songs_from_dir(dir_path: str | Path) -> dict[str, Song]:
    """Carga todas las canciones válidas en un directorio dado."""
    path = Path(dir_path)
    if not path.is_dir():
        raise NotADirectoryError(f"Directorio de canciones no encontrado: {path}")

    songs: dict[str, Song] = {}
    for json_file in sorted(path.glob("*.json")):
        song = load_song_from_file(json_file)
        songs[song.id] = song

    return songs
