# Sincronización móvil después de una pausa

Se encontraron y corrigieron dos discontinuidades del reloj de captura mientras se revisaba la generación de canciones. No se cambia el tamaño de los búferes ni la compensación elegida por el cantante. Estas correcciones pertenecen a la rama posterior a 0.3.1; el instalador público 0.3.1 no las incluye todavía.

## Secuencias que fallaban

**Pausar brevemente y continuar.** El puente WebRTC deja de enviar PCM mientras la canción está pausada. Si no llegaba ningún paquete durante una pausa corta, el receptor nativo no registraba el corte. Al continuar conservaba el origen anterior y trataba el salto como deriva lenta. La reproducción determinista de una pausa de 45 ms dejó el reloj 44,933 ms atrasado; señalar la discontinuidad deja un error lógico de 0 ms en ese mismo caso.

`UKaraokeMobileAudio.pas` conserva ahora un contador de entradas en pausa. El hilo receptor detecta el cambio aunque no reciba audio durante la pausa, o aunque pausar y reanudar sucedan entre dos iteraciones suyas. El siguiente bloque inicia un tramo nuevo. Una prueba con UDP real sobre localhost y una pausa observada de 49 ms marcó el corte y recibió el reloj reanudado a 3 ms del envío. Esa cifra incluye planificación del sistema; no mide latencia acústica.

**Recibir audio con un hueco, duplicado o reloj reiniciado.** El puente Python numeraba consecutivamente cada bloque recibido, aunque sus marcas de captura estuvieran separadas. Ahora usa `pts × time_base` de las tramas mono de 960 muestras a 48 kHz: conserva intervalos ausentes de 20 ms, descarta duplicados y marca el corte al reiniciar el reloj o sustituir la conexión. No une ventanas de análisis de dos tramos separados. La documentación de PyAV define las marcas de presentación y su unidad de tiempo, además del remuestreador usado por el puente. [Frame](https://pyav.org/docs/stable/api/frame.html) · [AudioResampler](https://pyav.org/docs/stable/api/audio.html)

## Verificación

- Quince pruebas del puente pasan con PyAV y aiortc reales: mono/estéreo, huecos, duplicados, reinicio de reloj, pausa, cambio de turno, conexión sustituida y WebRTC local con tono sintético.
- Diez conexiones WebRTC locales simultáneas mantienen canal y frecuencia durante veinte segundos, incluida la reconexión de la quinta voz: 10.223 tramas sonoras sin altura inesperada; la única discontinuidad de secuencia corresponde al reinicio deliberado de esa conexión. No son diez teléfonos físicos.
- El ensayo Pascal comprueba la pausa de 45 ms, ausencia de paquetes durante la pausa y pausa/reanudación inmediatas. Se incorpora al bloque de pruebas nativas de macOS del workflow de construcción; esa nueva ejecución en CI aún no se ha lanzado.
- El motor recompilado obtiene **10.000 puntos en los seis desfases compensados** (0, +50, +100, +200, −50 y −100 ms), frente a 0 en el control sin compensación. Con el análisis temporalmente ocupado mantiene el retorno sintético y vuelve a acumular puntos al liberarlo.
- La sesión completa pasa **21/21 controles en 32,88 s**: importar, encolar, cantar dos voces, plegar/restaurar el panel, cambiar de canción, cerrar y recuperar los turnos en orden sin reproducir automáticamente.
- Tres perfiles de Chrome conectados a una sesión real pasan confirmación tardía, respuesta perdida, edición conservada, desconexión simulada y cierre de sala. La prueba independiente de la ficha a 390/320 px se documenta en [mando móvil](mando-ux-2026-11-21.md).

Comandos ejecutados desde el proyecto:

```sh
uv run pytest -q tests/test_mobile_voice.py
uv run python scripts/test_mobile_voice_group.py --seconds 20 --output build/ux-next/mobile-voices.json
fpc -Funative -Fubuild/engine/src/lib/SDL2 -FUbuild/qa-audio -FEbuild/qa-audio "-Fl$(brew --prefix sdl2-compat)/lib" scripts/test_audio_mobile_clock.pas
build/qa-audio/test_audio_mobile_clock
uv run python scripts/test_audio_score_clock.py --engine build/engine/game/ultrastardx
uv run python scripts/test_session.py --engine build/engine/game/ultrastardx --check-panel --output build/ux-next/session-integrated.json
KARAOKE_ENGINE="$PWD/build/engine/game/ultrastardx" uv run --locked --with playwright python scripts/test_remote_browser.py --channel chrome --capture build/ux-next/remote-real
```

El motor probado tiene SHA-256 `32655ecaab435ba2340141efa2b099a2c0f7f935f6a9bd02633d5e21018a9b41`. Registros: `build/ux-next/{mobile-clock,score-clock,session-integrated,remote-real}.log`; muestras y comprobaciones de la sesión: `build/ux-next/session-integrated.json`. La compilación de desarrollo conserva los avisos de mínimo de macOS de las bibliotecas locales; no equivale a un paquete portable de distribución.

## Alcance físico

Se ejecuta en el Mac M4 real, pero la entrada de voz es sintética. El test del reloj y el de navegadores usan salida SDL simulada. La sesión integral usa la configuración de audio del motor de desarrollo; durante su comprobación se detectó la salida del sistema sin silenciar y se restableció inmediatamente el silencio. No se capturó voz ni se realizó otra medición acústica. El estado final de la salida es silenciado.

No se ha probado este cambio en móviles físicos, una red wifi real o Windows. La mejora acústica anterior de 73 a 57 ms corresponde a la medición física documentada en [retorno y puntuación](retorno-y-puntuacion.md). Las correcciones actuales evitan errores de sincronización; no demuestran otra reducción de esos 57 ms.
## Comprobación posterior: llegada diferida del último datagrama

La [ejecución 44942748050](https://github.com/AlexAmMo/karaoke/actions/runs/44942748050), sobre `c7d1dcb`, pasó Linux y Windows pero falló una prueba en macOS: al sustituir una entrada estéreo, el test esperaba secuencias `[3, 4]` y leyó `[3]`. Las otras 250 pruebas macOS pasaron. Esta ejecución se conserva como fallo; no se presenta como una validación completa.

Se reprodujo determinísticamente el caso aplazando la entrega del último datagrama al siguiente turno del bucle de eventos. El emisor de producción había enviado ambos números correctamente. El lector del test consultaba un socket no bloqueante y confundía «todavía no legible» con «ya no quedan paquetes». La reproducción falló con la misma aserción antes de corregir el lector.

El test espera ahora los paquetes requeridos con `loop.sock_recv` y un plazo global de dos segundos; después comprueba paquetes adicionales y conserva la igualdad exacta de secuencias. No añade una espera fija ni relaja el resultado esperado. La regresión diferida pasa, junto con las dieciséis pruebas de voz móvil y la suite local completa de **252 pruebas en 19,40 s**. El archivo de producción `src/karaoke/mobile_voice.py` no cambió. Esto corrige la sincronización del test, no aporta una nueva medición de latencia física.

El log fallido, el control rojo previo y los resultados posteriores están en `build/ci-mobile-voice-44942748050/`; `diagnosis.json` registra sus huellas. La revisión independiente y Ruff pasan. La comprobación posterior en los tres runners se registra en `docs/VALIDACION.md` cuando termine.
