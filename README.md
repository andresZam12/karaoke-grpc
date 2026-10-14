# Karaoke-gRPC 🎤🎶

**Karaoke-gRPC** es un sistema de karaoke colaborativo y sincronizado en tiempo real implementado con **Python 3.11+**, **gRPC (asyncio)** y una interfaz dual:
1. **Interfaz Terminal CLI (Rich)**: Visualización en terminal con acordes grandes, paneles dinámicos y métricas de reloj.
2. **Interfaz Web Interactiva (Vercel-ready)**: Frontend moderno con diseño oscuro, visualizador de audio, control de director y simulador multi-cliente con compensación de *Clock Skew*.

---

## 🏛️ Arquitectura del Sistema

```
                 +---------------------------------------+
                 |            SERVIDOR gRPC              |
                 |             (Puerto 50051)            |
                 |                                       |
                 |  +---------------+  +---------------+ |
                 |  | KaraokeService|  |  Room Manager  | |
                 |  +---------------+  +---------------+ |
                 |          |                  |         |
                 |          |             (Scheduler     |
                 |          |              LEAD_MS=700ms)|
                 +----------|------------------|---------+
                            |                  |
           +----------------+                  +----------------+
           | Sync (BiDi Stream)                | Join (Server Stream)
           | ClockPing / ClockPong             | SongEvent (Line/State/End)
           v                                   v
+-----------------------+             +-----------------------+
|  CLIENTE A (Terminal) |             |  CLIENTE B (Terminal) |
|  ClockSync (skew=0ms) |             | ClockSync(skew=+1500) |
|  Rich Display         |             |  Rich Display         |
+-----------------------+             +-----------------------+
```

---

## 📋 Tipos de Llamadas gRPC Implementadas

En este proyecto se aplican y demuestran los tres patrones fundamentales de comunicación en gRPC:

| Método RPC | Tipo de Comunicación | Descripción |
| :--- | :--- | :--- |
| `ListSongs` | **Unary** (1 petición -> 1 respuesta) | El cliente consulta el catálogo de canciones disponibles en el servidor. |
| `CreateRoom` | **Unary** (1 petición -> 1 respuesta) | Crea una sala para una canción y devuelve el `room_id` de 6 caracteres. |
| `Control` | **Unary** (1 petición -> 1 respuesta) | Modo director: envía acciones (`play`, `pause`, `restart`) a una sala. |
| `Join` | **Server Streaming** (1 petición -> flujo continuo) | El cliente se suscribe a los eventos en vivo (`SongEvent`) de la sala. |
| `Sync` | **Bidireccional** (flujo continuo <-> flujo continuo) | Intercambio de `ClockPing` y `ClockPong` para estimar RTT y offset. |

---

## ⏱️ Algoritmo de Sincronización de Reloj y Offset

Para lograr que los clientes muestren el acorde y la letra **exactamente al mismo milisegundo**, se utiliza una variante adaptada del **Algoritmo de Cristian**:

1. **Medición de RTT**:
   - El cliente envía un ping con su marca de tiempo local $t_0$ (`client_send_ms`).
   - El servidor responde de inmediato con su hora actual $t_{\text{server}}$ (`server_ms`) y el eco de $t_0$.
   - Al recibir el pong en la hora local $t_1$, el cliente calcula el tiempo de ida y vuelta:
     $$\text{RTT} = t_1 - t_0$$
2. **Estimación del Offset**:
   - Asumiendo latencia simétrica en la red:
     $$\text{offset} = t_{\text{server}} + \frac{\text{RTT}}{2} - t_1$$
     *(Un offset positivo indica que el servidor va adelantado respecto al reloj del cliente).*
3. **Filtro de Menor RTT (Ventana Deslizante)**:
   - Al conectar, el cliente envía **8 pings iniciales** espaciados por 200 ms.
   - Mantiene una cola circular con las últimas 8 muestras y selecciona como offset activo el de la muestra con **menor RTT**, minimizando el error por jitter de red.
   - Posteriormente, envía un ping de refresco cada 5 segundos.
4. **Hora Estimada del Servidor**:
   $$\text{server\_now\_ms}() = \text{local\_now\_ms}() + \text{offset}$$
5. **Anticipación y Renderizado (Lead Time)**:
   - El servidor transmite las líneas con un margen de anticipación `LEAD_MS = 700 ms`.
   - Cada cliente espera hasta que $\text{server\_now\_ms}() \ge \text{play\_at\_server\_ms}$, garantizando que todos los terminales rendericen la línea en simultáneo.

---

## 🚀 Requisitos e Instalación

### 1. Clonar el repositorio y crear entorno virtual
```bash
git clone https://github.com/andresZam12/karaoke-grpc.git
cd karaoke-grpc

python -m venv .venv
# En Windows:
.venv\Scripts\activate
# En Linux/macOS:
source .venv/bin/activate
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Compilar el contrato gRPC (Protobuf)
```bash
make proto
```
*(O de forma manual)*:
```bash
python -m grpc_tools.protoc -I proto --python_out=generated --grpc_python_out=generated proto/karaoke.proto
```

---

## 🎮 Demostración en Vivo (4 Terminales)

Abre 4 terminales independientes en el directorio del proyecto con el entorno virtual activo:

### Terminal 1: Servidor gRPC
Inicia el servidor en el puerto 50051:
```bash
python -m server.main
# O mediante el Makefile:
make server
```

### Terminal 2: Crear Sala y Listar Canciones
Consulta las canciones y crea una sala con la canción `estrellita`:
```bash
# 1. Listar canciones
python -m client.main list

# 2. Crear sala
python -m client.main create --song estrellita
```
*Copia el ID de 6 caracteres generado (por ejemplo: `AB12CD`).*

### Terminal 3: Cliente 1 (Reloj normal)
```bash
python -m client.main join --room AB12CD --name "Cantante Real"
```

### Terminal 4: Cliente 2 (Simulando reloj adelantado +1500 ms)
```bash
python -m client.main join --room AB12CD --name "Cantante Desfasado" --fake-skew-ms 1500
```

*(Opcional: Terminal 5 con reloj retrasado):*
```bash
python -m client.main join --room AB12CD --name "Cantante Retrasado" --fake-skew-ms -800
```

### Iniciar la Reproducción (Modo Director)
En la **Terminal 2**, ejecuta:
```bash
python -m client.main control --room AB12CD --action play
```
> **Resultado**: ¡Ambos clientes en las terminales 3 y 4 mostrarán la letra y el acorde grande exactamente al mismo instante visual!
>
> Puedes pausar con `--action pause` y reiniciar con `--action restart`.

---

## 🧪 Pruebas Automatizadas

El proyecto cuenta con una suite completa de pruebas unitarias y de integración sobre un servidor gRPC real en puerto efímero:

```bash
pytest -v
# O usando el Makefile:
make test
```

### Casos de prueba incluidos:
1. `test_song_validation`: Valida que archivos JSON con marcas de tiempo $t$ no crecientes sean rechazados con error claro.
2. `test_load_default_songs`: Comprueba la integridad de las canciones de dominio público en `songs/`.
3. `test_room_lifecycle`: Valida la transición de estados `WAITING -> PLAYING -> PAUSED -> RESTART` y avance de `position_s`.
4. `test_join_unknown_room`: Verifica que unirse a una sala inexistente retorne código `NOT_FOUND`.
5. `test_late_joiner`: Comprueba que un cliente conectado a mitad de reproducción reciba el estado actual y la línea activa de inmediato.
6. `test_clock_offset`: Simula un cliente con `--fake-skew-ms +1500` y verifica que el offset converja dentro de $\pm 30$ ms.
7. `test_multi_client_sync`: **(Test crítico)** 3 clientes simultáneos con desfases de $-800$ ms, $0$ ms y $+1200$ ms se unen a la misma sala; se valida que para cada línea la diferencia máxima en el instante de renderizado sea $\le 60$ ms.

---

## 🌐 Interfaz Web y Despliegue en Vercel

El proyecto incluye un frontend web interactivo dentro del directorio [`web/`](file:///c:/Users/andre/INGENIERIA_SOFTWARE/S7/POWeb/karaoke-grpc/web/), configurado para despliegue inmediato en **Vercel** mediante [`vercel.json`](file:///c:/Users/andre/INGENIERIA_SOFTWARE/S7/POWeb/karaoke-grpc/vercel.json).

### Características del Frontend Web:
- **Hero Stage con Acordes en Vivo**: Muestra el acorde musical resaltado con animaciones y tamaño prominente.
- **Visualizador de Audio Dinámico**: Animación de barras reactivas al ritmo de la música.
- **Panel del Director**: Selector de canciones (`Estrellita`, `Campanero`), botones de reproducción, pausa, reinicio y generador de salas.
- **Simulador Multi-Cliente en Tiempo Real**: Visualización lado a lado de 3 clientes con diferentes desajustes temporales ($-800$ ms, $0$ ms, $+1500$ ms), demostrando cómo el algoritmo compensa el desajuste para que todos vean la línea y acorde al mismo instante.
- **Tabla de Protocolo gRPC**: Explicación interactiva de los 5 RPCs del contrato.

### Probar la Interfaz Web Localmente:
```bash
python -m http.server 3000 --directory web
```
Abre en tu navegador: [http://localhost:3000](http://localhost:3000)

### Desplegar en Vercel:
1. Conecta tu repositorio de GitHub [andresZam12/karaoke-grpc](https://github.com/andresZam12/karaoke-grpc) en tu panel de Vercel.
2. Vercel detectará automáticamente el archivo `vercel.json` y desplegará la carpeta `web/` como aplicación web con cero configuración adicional.
