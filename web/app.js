/**
 * Karaoke-gRPC Web Client & Clock Synchronization Simulator
 * Demuestra la arquitectura distribuida, la compensación de Clock Skew
 * y el renderizado sincronizado de acordes y letras para Vercel.
 */

// Catálogo de canciones de dominio público
const SONGS = {
  estrellita: {
    id: "estrellita",
    title: "Estrellita, ¿dónde estás?",
    artist: "Tradicional",
    duration_s: 30.0,
    lines: [
      { t: 0.0, chord: "C", lyric: "Estrellita, ¿dónde estás?" },
      { t: 3.0, chord: "F", lyric: "Me pregunto qué serás," },
      { t: 6.0, chord: "C", lyric: "En el cielo y en el mar," },
      { t: 9.0, chord: "G", lyric: "Un diamante de verdad." },
      { t: 12.0, chord: "C", lyric: "Estrellita, ¿dónde estás?" },
      { t: 15.0, chord: "F", lyric: "Me pregunto qué serás." },
      { t: 18.0, chord: "C", lyric: "Cuando el sol se fue a dormir," },
      { t: 21.0, chord: "G", lyric: "Y nada alumbra por aquí," },
      { t: 24.0, chord: "C", lyric: "Muestras tú tu resplandor," },
      { t: 27.0, chord: "Am", lyric: "Brillas, brillas con amor." }
    ]
  },
  campanero: {
    id: "campanero",
    title: "Martinillo (Campanero)",
    artist: "Tradicional",
    duration_s: 27.5,
    lines: [
      { t: 0.0, chord: "C", lyric: "Martinillo, martinillo," },
      { t: 3.5, chord: "C", lyric: "¿Dónde estás? ¿Dónde estás?" },
      { t: 7.0, chord: "F", lyric: "Toca la campana," },
      { t: 10.5, chord: "C", lyric: "Toca la campana," },
      { t: 14.0, chord: "G", lyric: "Din, don, dan," },
      { t: 17.5, chord: "C", lyric: "Din, don, dan." },
      { t: 21.0, chord: "Am", lyric: "Suenan las campanas," },
      { t: 24.5, chord: "C", lyric: "Al amanecer." }
    ]
  }
};

const LEAD_MS = 700;

const RoomState = {
  ROOM_WAITING: 1,
  ROOM_PLAYING: 2,
  ROOM_PAUSED: 3,
  ROOM_FINISHED: 4
};

// Estado de la sala activa
const room = {
  id: "GRPC51",
  songId: "estrellita",
  state: RoomState.ROOM_WAITING,
  position_s: 0.0,
  start_ms: 0,
  activeTimers: []
};

// Configuración de los 3 clientes simulados con clock skew
const simulatedClients = [
  { id: 1, name: "Cliente 1 (Local)", skew: 0, rtt: 1.2 },
  { id: 2, name: "Cliente 2 (+1500ms)", skew: 1500, rtt: 1.8 },
  { id: 3, name: "Cliente 3 (-800ms)", skew: -800, rtt: 0.9 }
];

// Elementos del DOM
const elements = {
  roomId: document.getElementById("current-room-id"),
  stateBadge: document.getElementById("room-state-badge"),
  stageCard: document.querySelector(".stage-card"),
  songTitle: document.getElementById("stage-song-title"),
  songArtist: document.getElementById("stage-song-artist"),
  heroChordBox: document.getElementById("hero-chord-box"),
  heroChord: document.getElementById("hero-chord"),
  prevLyric: document.getElementById("prev-lyric-line"),
  currentLyric: document.getElementById("current-lyric-line"),
  nextChordTag: document.getElementById("next-chord-tag"),
  nextLyricText: document.getElementById("next-lyric-text"),
  progressBarFill: document.getElementById("progress-bar-fill"),
  timeCurrent: document.getElementById("time-current"),
  timeDuration: document.getElementById("time-duration"),
  songSelect: document.getElementById("song-select"),
  btnPlay: document.getElementById("btn-play"),
  btnPause: document.getElementById("btn-pause"),
  btnRestart: document.getElementById("btn-restart"),
  btnNewRoom: document.getElementById("btn-new-room")
};

function formatTime(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(1);
  return `${String(mins).padStart(2, "0")}:${secs < 10 ? "0" : ""}${secs}`;
}

function generateRoomId() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let result = "";
  for (let i = 0; i < 6; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return result;
}

function updateStateBadge() {
  elements.stateBadge.className = "room-state-badge";
  elements.stageCard.classList.remove("playing");

  if (room.state === RoomState.ROOM_WAITING) {
    elements.stateBadge.classList.add("state-waiting");
    elements.stateBadge.textContent = "EN ESPERA";
  } else if (room.state === RoomState.ROOM_PLAYING) {
    elements.stateBadge.classList.add("state-playing");
    elements.stateBadge.textContent = "● REPRODUCIENDO";
    elements.stageCard.classList.add("playing");
  } else if (room.state === RoomState.ROOM_PAUSED) {
    elements.stateBadge.classList.add("state-paused");
    elements.stateBadge.textContent = "PAUSADA";
  } else if (room.state === RoomState.ROOM_FINISHED) {
    elements.stateBadge.classList.add("state-finished");
    elements.stateBadge.textContent = "FINALIZADA";
  }
}

function loadSongMetadata() {
  const song = SONGS[room.songId];
  elements.songTitle.textContent = song.title;
  elements.songArtist.textContent = `${song.artist} (Dominio Público)`;
  elements.timeDuration.textContent = formatTime(song.duration_s);
  elements.timeCurrent.textContent = formatTime(room.position_s);
  elements.progressBarFill.style.width = "0%";
}

function clearScheduler() {
  room.activeTimers.forEach((timer) => clearTimeout(timer));
  room.activeTimers = [];
}

/**
 * Planificador central del servidor gRPC (Scheduler)
 * Emite cada línea a los clientes con LEAD_MS de anticipación.
 */
function startScheduler(wasPaused) {
  clearScheduler();
  const song = SONGS[room.songId];
  const now = Date.now();

  const linesToSchedule = wasPaused
    ? song.lines.filter((l) => l.t > room.position_s)
    : song.lines.filter((l) => l.t >= room.position_s);

  // Si reanuda tras pausa, emitir primero la línea actual con play_at = now + LEAD_MS
  if (wasPaused) {
    let currentIdx = -1;
    for (let i = 0; i < song.lines.length; i++) {
      if (song.lines[i].t <= room.position_s) currentIdx = i;
      else break;
    }
    if (currentIdx >= 0) {
      dispatchLineEvent(song, currentIdx, now + LEAD_MS);
    }
  }

  linesToSchedule.forEach((line) => {
    const idx = song.lines.indexOf(line);
    const playAt = room.start_ms + Math.floor(line.t * 1000);
    const wakeAt = playAt - LEAD_MS;
    const delay = Math.max(0, wakeAt - Date.now());

    const timer = setTimeout(() => {
      if (room.state === RoomState.ROOM_PLAYING) {
        dispatchLineEvent(song, idx, playAt);
      }
    }, delay);

    room.activeTimers.push(timer);
  });

  // Temporizador para finalizar la canción
  const endAt = room.start_ms + Math.floor(song.duration_s * 1000);
  const endDelay = Math.max(0, endAt - Date.now());
  const endTimer = setTimeout(() => {
    if (room.state === RoomState.ROOM_PLAYING) {
      room.state = RoomState.ROOM_FINISHED;
      room.position_s = song.duration_s;
      updateStateBadge();
      elements.currentLyric.textContent = "🎉 ¡Canción terminada! Gracias por cantar. 🎉";
      elements.heroChord.textContent = "★";
      elements.nextChordTag.textContent = "";
      elements.nextLyricText.textContent = "Fin de la presentación";
    }
  }, endDelay);

  room.activeTimers.push(endTimer);
}

/**
 * Emite el evento a cada cliente y aplica la compensación de reloj
 */
function dispatchLineEvent(song, lineIdx, playAtServerMs) {
  const line = song.lines[lineIdx];
  const nextLine = lineIdx + 1 < song.lines.length ? song.lines[lineIdx + 1] : null;

  simulatedClients.forEach((client) => {
    // Reloj local del cliente con su fake skew simulado
    const localNow = Date.now() + client.skew;

    // Offset calculado por el algoritmo de Cristian: offset = server_ms + (rtt/2) - local_now
    // En régimen estacionario: offset = -client.skew
    const offset = -client.skew;

    // Hora estimada del servidor por este cliente:
    // server_now_ms = local_now + offset = (Date.now() + skew) + (-skew) = Date.now()
    const clientServerNow = localNow + offset;

    // Tiempo de espera exacto
    const waitMs = Math.max(0, playAtServerMs - clientServerNow);

    setTimeout(() => {
      if (room.state === RoomState.ROOM_PLAYING) {
        // Render en el cliente específico
        renderClientOutput(client.id, line.chord, line.lyric, offset, client.rtt);

        // Si es el cliente principal, actualizar el Hero Stage
        if (client.id === 1) {
          renderHeroStage(line, nextLine, lineIdx, song);
        }
      }
    }, waitMs);
  });
}

function renderHeroStage(line, nextLine, lineIdx, song) {
  // Animar acorde
  elements.heroChordBox.classList.remove("pop");
  void elements.heroChordBox.offsetWidth; // Trigger reflow
  elements.heroChordBox.classList.add("pop");

  elements.heroChord.textContent = line.chord;
  elements.currentLyric.textContent = line.lyric;

  if (lineIdx > 0) {
    elements.prevLyric.textContent = song.lines[lineIdx - 1].lyric;
  } else {
    elements.prevLyric.textContent = "♫ Inicio de la canción ♫";
  }

  if (nextLine) {
    elements.nextChordTag.textContent = `[${nextLine.chord}]`;
    elements.nextLyricText.textContent = nextLine.lyric;
  } else {
    elements.nextChordTag.textContent = "";
    elements.nextLyricText.textContent = "--- Última línea ---";
  }
}

function renderClientOutput(clientId, chord, lyric, offset, rtt) {
  const card = document.getElementById(`card-client-${clientId}`);
  const chordEl = document.getElementById(`c${clientId}-chord`);
  const lyricEl = document.getElementById(`c${clientId}-lyric`);
  const offsetEl = document.getElementById(`c${clientId}-offset`);
  const rttEl = document.getElementById(`c${clientId}-rtt`);

  if (!card) return;

  chordEl.textContent = chord;
  lyricEl.textContent = lyric;
  offsetEl.textContent = `${offset >= 0 ? "+" : ""}${offset.toFixed(1)} ms`;
  rttEl.textContent = `${rtt.toFixed(1)} ms`;

  card.classList.remove("flash");
  void card.offsetWidth;
  card.classList.add("flash");
}

/* Loop de animación para la barra de progreso */
function animationLoop() {
  if (room.state === RoomState.ROOM_PLAYING) {
    const elapsed = Math.max(0, (Date.now() - room.start_ms) / 1000.0);
    const song = SONGS[room.songId];
    const current = Math.min(elapsed, song.duration_s);

    elements.timeCurrent.textContent = formatTime(current);
    const percent = Math.min(100, (current / song.duration_s) * 100);
    elements.progressBarFill.style.width = `${percent}%`;
  }
  requestAnimationFrame(animationLoop);
}

/* Control actions */
function handlePlay() {
  if (room.state === RoomState.ROOM_PLAYING) return;

  const wasPaused = room.state === RoomState.ROOM_PAUSED;
  if (room.state === RoomState.ROOM_FINISHED) {
    room.position_s = 0.0;
  }

  const now = Date.now();
  room.start_ms = now + LEAD_MS - Math.floor(room.position_s * 1000);
  room.state = RoomState.ROOM_PLAYING;
  updateStateBadge();
  startScheduler(wasPaused);
}

function handlePause() {
  if (room.state !== RoomState.ROOM_PLAYING) return;

  const song = SONGS[room.songId];
  clearScheduler();
  const elapsed = (Date.now() - room.start_ms) / 1000.0;
  room.position_s = Math.max(0, Math.min(elapsed, song.duration_s));
  room.state = RoomState.ROOM_PAUSED;
  updateStateBadge();
}

function handleRestart() {
  clearScheduler();
  room.position_s = 0.0;
  room.state = RoomState.ROOM_WAITING;
  updateStateBadge();
  loadSongMetadata();

  const song = SONGS[room.songId];
  elements.heroChord.textContent = song.lines[0].chord;
  elements.prevLyric.textContent = "---";
  elements.currentLyric.textContent = 'Presiona "Reproducir" para iniciar el karaoke';
  elements.nextChordTag.textContent = `[${song.lines[0].chord}]`;
  elements.nextLyricText.textContent = song.lines[0].lyric;

  simulatedClients.forEach((c) => {
    document.getElementById(`c${c.id}-chord`).textContent = song.lines[0].chord;
    document.getElementById(`c${c.id}-lyric`).textContent = "En espera de reproducción...";
  });
}

function handleNewRoom() {
  handleRestart();
  room.id = generateRoomId();
  elements.roomId.textContent = room.id;
}

function handleSongChange() {
  handleRestart();
  room.songId = elements.songSelect.value;
  loadSongMetadata();
  handleRestart();
}

// Event Listeners
elements.btnPlay.addEventListener("click", handlePlay);
elements.btnPause.addEventListener("click", handlePause);
elements.btnRestart.addEventListener("click", handleRestart);
elements.btnNewRoom.addEventListener("click", handleNewRoom);
elements.songSelect.addEventListener("change", handleSongChange);

// Atajo de teclado: Barra espaciadora para reproducir/pausar
window.addEventListener("keydown", (e) => {
  if (e.code === "Space" && e.target.tagName !== "SELECT" && e.target.tagName !== "INPUT") {
    e.preventDefault();
    if (room.state === RoomState.ROOM_PLAYING) {
      handlePause();
    } else {
      handlePlay();
    }
  }
});

// Inicialización
handleNewRoom();
loadSongMetadata();
updateStateBadge();
requestAnimationFrame(animationLoop);
