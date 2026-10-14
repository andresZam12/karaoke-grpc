"""Pruebas unitarias y de integración para karaoke-grpc."""
import pytest
from server.songs import validate_and_parse_song, load_songs_from_dir


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
