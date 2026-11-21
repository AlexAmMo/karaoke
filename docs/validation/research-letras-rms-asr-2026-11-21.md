# Comparación de letras con cortes RMS: 16 condiciones completas

Se completaron las **dieciséis condiciones de cuatro canciones**, con Turbo CPU int8, y se congelaron las salidas antes de evaluar. La comparación primaria, mix-rms frente a mix-native, reduce el WER agrupado del **28,537 % al 17,598 %**, pero **no se amplía a las otras 36 canciones**: «11 y 6» empeora 4,938 puntos porcentuales, por encima de los 2 puntos permitidos por el criterio previo. Ninguna de las dieciséis transcripciones alcanza WER ≤ 1 %. La segmentación aporta una mejora parcial, no letras casi perfectas.

El plan v3 conserva cuatro brazos completos, sin escoger uno distinto por canción: mix-native, mix-rms, vocals-native y vocals-rms. Las identidades son Amorfoda, 11 y 6, Mr. Fancy Pants y Northern Star; pertenecen al piloto de desarrollo anterior, no a un conjunto reservado. Las otras 36 identidades siguen explícitamente ausentes en cada brazo. El ensayo sólo compara reconocimiento acústico de letras y sus tiempos; no genera mapas musicales ni evalúa la cadena de corroboración de letras del producto.

La ejecución se hizo en el MacBook Pro M4 real, con audio guardado y la salida silenciada, un proceso CPU a la vez. Se conservaron los fallos de carga de v1 y de serialización de v2 antes del control técnico y la cohorte correctos de v3. El segundo de silencio del control produjo cinco palabras: terminar técnicamente no demuestra exactitud. Todos los resultados de este documento **preceden a la guardia de silencio incorporada después en el commit `551247c`**; no se atribuyen a esa mejora posterior.

## Pesos, función de producción y reloj

Se ha localizado el Turbo real en la caché local, revisión `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf` de `mobiuslabsgmbh/faster-whisper-large-v3-turbo`. Su `model.bin` ocupa 1.617.884.929 bytes y tiene SHA-256 `e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da`. El plan guarda también los hashes de configuración, preprocesador, tokenizer y vocabulario. La carpeta antigua `build/generation-bench/model` corresponde a Small y no se utiliza. No se descargaron otros pesos.

Cada condición reutilizó `generation_worker.transcribe` con sus opciones exactas: CPU int8, tres hilos, beam cinco, tiempos de palabra, idioma fijo, VAD desactivado y condicionamiento por texto anterior desactivado. Se pasa un envoltorio del modelo que registra cada segmento crudo antes del filtro de producción. Así se conservan puntuación, palabras de duración no positiva, repeticiones y resultados que crucen una frontera; las líneas filtradas de la app se guardan por separado.

La mezcla se decodifica con el mismo comando FFmpeg de `split_vocals`: primer flujo de audio, 44.100 Hz, dos canales y WAV FLOAT. La media float32 entre canales y `scipy.signal.resample_poly` son los mismos de `transcribe`; se preparan una sola vez por fuente y ambos brazos leen ese mismo WAV mono de 16 kHz. El brazo nativo recibe toda la onda. El RMS utiliza los cortes de voz ya fijados y transforma cada frontera mediante `round(muestra × 16000 / 44100)`. Se registra cualquier recorte final. Los tiempos reconocidos vuelven al reloj absoluto sumando la muestra inicial dividida por 16.000, sin desplazar ni estirar el audio.

Este detalle afecta al piloto: el lector directo de MP3 de SoundFile informa 79,601882 s para Mr. Fancy Pants, mientras que el reloj decodificado que produjo su voz es de aproximadamente 79,5167 s. No se mezclan ambos relojes: se utiliza FFmpeg como en producción y se comprueba la longitud resultante. Las ocho ondas preparadas coinciden exactamente entre mezcla y voces:

| Grabación | Muestras por fuente a 16 kHz | Fuentes |
|---|---:|---:|
| Amorfoda | 2.829.677 | 2 |
| 11 y 6 | 4.241.450 | 2 |
| Mr. Fancy Pants | 1.272.268 | 2 |
| Northern Star | 3.042.764 | 2 |

La preparación procesa una fuente a la vez, antes del modelo, y rechaza entradas de más de 300 s, más de dos canales o más de 48 kHz. El piloto llegó a **299,5 MiB RSS** y terminó en **2,355 s**, incluida la decodificación de las cuatro mezclas. Es coste de preparación, no de reconocimiento. Los WAV y sus hashes quedan en `audio-frozen.json`.

## Controles y protocolo original de ejecución (v1)

Seis controles ligeros verifican el reloj entero compartido, la entrada nativa completa, la conservación de palabras que cruzan el corte, las repeticiones y duraciones no positivas, y la llamada real a producción con reconocedor simulado. Este último comprueba todos los argumentos y que la captura cruda precede al filtrado. Dos controles adicionales con audio sintético estéreo de 44.100 y 48.000 Hz comparan el remuestreo con la entrada recibida por esa función de producción: los resultados son idénticos byte a byte, incluidos extremos y longitud no divisible. No importan el reconocedor real ni Torch.

Un segundo agente revisó estáticamente la captura, la suma del tiempo absoluto, el redondeo compartido, el recorte final registrado y el requisito del control supervisado previo, sin identificar un defecto en esas rutas. No repitió los controles ni ejecutó ASR. Ruff y `git diff --check` pasan.

El protocolo inicial v1 crea un proceso nuevo por canción y condición. Reutiliza el supervisor probado de `yourmt3_notes.py` y la lectura `libproc` de `lead_vocals.py`, ambos firmados en el plan. Observa RSS y huella física cada 50 ms, corta al alcanzar 2 GiB o perder la telemetría, recoge el proceso y detiene la cohorte si hay fallo. Cada condición tiene un máximo de 600 s. Este muestreo no es un límite de asignación del sistema ni garantiza que el pico entre muestras no lo supere. Un fichero de pesos de 1,618 GB puede necesitar memoria adicional durante la conversión int8.

Antes de las dieciséis condiciones, `synthetic` debe cargar esos mismos pesos en un proceso supervisado y recorrer la API con un segundo de silencio. Sólo si termina y queda recogido escribe `synthetic-frozen.json`; `execute` exige ese resultado de su mismo plan. Ese control comprueba carga/API, no la memoria máxima de una canción ni calidad de letra. **En v1 se ejecutó una vez y fue detenido antes de completar la carga; `execute` no se inició para ese plan.** La ejecución se coordinó con el único proceso de inferencia del Mac.

Los **20–30 minutos** propuestos son una estimación basada en tiempos anteriores de Turbo de aproximadamente 70–100 s por grabación, con sobrecoste desconocido de carga y fragmentación. No son una medición de este ensayo. Los dieciséis topes individuales suman 160 minutos. No se cambiará el presupuesto después de ver una letra de referencia; cualquier nueva configuración necesitará otro plan y conservará la anterior.

```sh
# Ya completados sin modelos:
build/generation-bench/env/bin/python scripts/experiments/rms_vad_asr.py selftest
build/generation-bench/env/bin/python scripts/experiments/rms_vad_asr.py plan
build/generation-bench/env/bin/python scripts/experiments/rms_vad_asr.py prepare

# Control ejecutado una vez: falló por el límite; no repetir en este directorio.
build/generation-bench/env/bin/python scripts/experiments/rms_vad_asr.py synthetic
# No ejecutado: exige un control sintético exitoso del mismo plan.
build/generation-bench/env/bin/python scripts/experiments/rms_vad_asr.py execute
```

El directorio v1 es inmutable; para reproducir preparación se debe elegir un directorio nuevo mediante `--output`. La evaluación de letras se ejecutó por separado en v3, después de congelar todas las salidas. Esta fase no implementa ni modifica el medidor.

| Artefacto | SHA-256 |
|---|---|
| Adaptador y snapshot | `904b564f405c68b49587a848f11fdd7e1b9460e979ba4cab13bd0a8a7b3e2631` |
| Plan previo | `6c7dee80fb1b0fd08647a936e503cdd2e2ee37f2108ea308c8afb36e8082d617` |
| Audio preparado congelado | `0c2d428579d5543b3a63bca48be80da650cbdfdf2adf9bdec04c2e8c11c2dbed` |
| Auditoría de preparación | `334ad5ec2c68f17ddc48fcb21d8013633b0c00804e2316b15c99bb3a845b0276` |

`preparation-audit.json` conserva además comandos y la instalación de FFmpeg observada **después** de la preparación: versión 9.0.1, SHA-256 `9f5ddd4f8b36eb07b0c5d60ab6ea1e618bedd70bc45feab82b4dc23be1596ad1`. El binario externo no se había inventariado en el plan previo; esta comprobación posterior no se presenta como una firma previa ni modifica el plan congelado. También verifica hashes y geometría de los ocho WAV. Ninguna fuente de audio o parámetro se seleccionó consultando letras humanas.

## Protocolo de evaluación fijado antes de inferir

Se añade `scripts/experiments/rms_vad_asr_evaluate.py` y un protocolo independiente, `v1/evaluation-protocol.json`, SHA-256 `2a57f55b53654c146bc031a956c8f7328b48cc326094024b8c29337107463cfa`. Este archivo enlaza el plan y el audio preparados sin modificarlos. Registra únicamente rutas y hashes previamente firmados de las referencias; todavía no abre sus letras.

La medida primaria es el **WER de `product_lines`**, el texto que conserva el flujo de la app, comparando mix-rms contra mix-native. Se informarán las cuatro parejas individualmente, sus diferencias, mejoras/retrocesos/empates, mediana y WER agrupado por número de palabras de referencia. Los otros dos brazos se publicarán completos. El **WER de `raw_words`** será una medida adicional para mostrar el efecto del filtro; no sustituirá al primario ni se elegirá según cuál favorezca cada canción.

Para ambas vistas se reutilizan la normalización y el WER del medidor común: NFKC, casefold, tokens alfanuméricos, acentos y repeticiones conservados. Si una unidad ASR contiene varios tokens, todos heredan su inicio; no se inventan tiempos internos. Se publican sustituciones (S), eliminaciones (D), inserciones (I), coincidencias (C) y tamaños de referencia/hipótesis. El recuento adicional reproduce el mismo desempate de la alineación común —diagonal, eliminación, inserción— y comprueba que S+D+I coincide con sus errores y C con sus coincidencias. Un texto completado pero vacío cuenta como D igual a todas las palabras de referencia, WER de 1 y tiempo sin coincidencias.

La matriz conserva **40 identidades por brazo**: 160 condiciones, de las cuales sólo dieciséis están previstas en este piloto. Las 36 identidades fuera del piloto por brazo permanecen como faltantes; una condición prevista que falle tampoco desaparece. Su WER no se calcula —se guarda `null`, no cero— y no cuenta como éxito. Las estadísticas de WER identifican explícitamente cuántas salidas se midieron sobre 40: los resultados de cuatro canciones no se presentan como cobertura completa. El CSV tendrá una fila por vista y condición, incluidas las ausentes; el JSON conserva además los detalles temporales.

El tiempo se mide únicamente entre palabras léxicamente coincidentes de la misma alineación, con inicio absoluto, p50/p90 del error y mediana con signo por tercios. Se conserva el número y fracción de palabras de referencia que pudieron coincidir, así como índices y diferencias de cada pareja, para no confundir pocas coincidencias bien alineadas con una letra completa. No se ajusta un desplazamiento ni se estira el reloj. Estas métricas de letras y tiempos no prueban mapas musicales casi perfectos.

`freeze` firma las predicciones completas y el estado final de los procesos intentados antes de que `evaluate` lea las referencias. Rechaza un directorio de proceso que no tenga recogida confirmada. También conserva evidencias parciales de una condición fallida. La ejecución incompleta puede cerrarse con sus faltantes explícitos; no se evalúan sólo sus fragmentos favorables. El evaluador pasa seis controles de S/D/I —incluidos repetición, vacío y desempate—, un desplazamiento sintético sin corregir y la normalización común, sin modelos ni letras humanas.

```sh
# Sólo después de terminar o detener y recoger todos los procesos del ensayo:
build/generation-bench/env/bin/python scripts/experiments/rms_vad_asr_evaluate.py freeze
build/generation-bench/env/bin/python scripts/experiments/rms_vad_asr_evaluate.py evaluate
```

Se ha inspeccionado estáticamente `faster-whisper 1.2.1`: `Word` y `Segment` están declarados como dataclasses, y `asdict(Segment)` convierte recursivamente sus palabras a diccionarios. Un control extraído exclusivamente de esas dos declaraciones confirma que el resultado anidado se serializa a JSON; no importa `faster_whisper` ni CTranslate2. Queda registrado en `v1/faster-whisper-types-audit.json`, SHA-256 `4e1b6ed505a19a04be4159b1dbcdb13dbf721be700687527dc83cf6522a86d95`. El módulo inspeccionado tiene SHA-256 `5d5ffb00018561d3d529b2c72e1d9f5fff055bea725f3cccc7c6c67f5cc8ffe4`. La rama alternativa `_asdict()` del adaptador no garantiza convertir `Word` anidados de versiones antiguas basadas en namedtuple; esa compatibilidad no se afirma. El ensayo exige la versión 1.2.1 fijada en su plan y utiliza la rama dataclass.

## Resultado del control sintético v1 con los pesos reales

Una vez liberado el proceso de inferencia anterior, se verificaron los hashes de las cuatro fuentes firmadas y se mantuvo silenciada la salida del Mac. Se ejecutó únicamente `synthetic` con el plan v1, Turbo CPU int8 y el presupuesto inicial de 2.147.483.648 bytes. El supervisor terminó el proceso con **SIGKILL, salida -9**, al observar una superación del presupuesto. Lo recogió y una consulta posterior del PID específico confirmó que ya no existía. No se repitió el intento, no se aumentó la cuota y no se inició ninguna de las dieciséis transcripciones.

| Medida del control | Resultado |
|---|---:|
| Tiempo supervisado | 1,726 s |
| Muestras de recursos | 33 |
| Máximo RSS observado | 2.149,234 MiB |
| Máxima huella física observada | 2.122,518 MiB |
| Umbral de parada | 2.048 MiB |
| Estado del proceso | Recogido, PID ausente |

Existe `before-model.json`, pero no `after-model.json`, predicción ni `synthetic-frozen.json`. La fase delimitada comprende la importación del reconocedor y la construcción del modelo; los marcadores no permiten atribuir por separado el máximo a la importación, lectura de pesos o conversión int8. Sí muestran que no se alcanzó la llamada a transcribir. La diferencia entre el umbral y el máximo observado recuerda que el supervisor toma muestras: **2 GiB no es un techo de asignación impuesto por el sistema**.

La evidencia está en `v1/synthetic-control/{before-model.json,resources.json,resources.jsonl,silence.wav}`, `v1/synthetic-launch.log` y `v1/synthetic-failed-assessment.json`, que enlaza sus hashes, confirma el cierre y registra cero reintentos. El fallo mide viabilidad de carga bajo esta configuración y presupuesto; no permite calcular WER, valorar la segmentación ni declarar que el reconocedor sea inviable con otras configuraciones. El generador, plan, ocho audios y protocolo de evaluación permanecen intactos.

## V2: presupuesto revisado y fallo de serialización

La [revisión de recursos de Turbo](research-recursos-turbo-2026-11-21.md) inspeccionó metadatos de tensores y fuentes de CTranslate2, además de medir sólo las importaciones. La envolvente orientativa de 3.518,55 MiB motiva **un único control nuevo de 4.096 MiB y 120 s**, con aproximadamente 577,45 MiB de margen respecto de esa estimación. No es una cota formal ni una prueba de viabilidad. El intento v2 se detuvo ante fallo, sin otra subida de cuota ni ejecución automática de las dieciséis condiciones.

`v2/plan.json` fija cuota y plazo; el supervisor los recibe desde ese archivo mediante `run_planned_worker`. El control sin modelo usa un supervisor simulado y verifica la propagación de 2/4 GiB, 120 s para el control y 600 s para una eventual condición completa. Los siete controles ligeros y Ruff pasan. Las fuentes del supervisor `yourmt3_notes.py` (`0a36fac…`) y del monitor `lead_vocals.py` (`5cc80ce…`) no cambian. Se añade únicamente un marcador `after-import.json` entre importación y construcción para precisar la fase si ocurre otro fallo.

Los ocho WAV se verificaron por hash y geometría y se reutilizan por sus rutas originales, sin copiarlos ni recodificarlos. El nuevo `audio-frozen.json` enlaza tanto el plan v2 como la procedencia v1. Coinciden exactamente modelo, opciones de decodificación, idiomas, identidades, cortes y filas de audio. Las reglas del protocolo de evaluación son idénticas, excluidos fecha y enlaces a las nuevas entradas. `v2/preflight-audit.json` comprueba estas igualdades y que los **28 archivos de v1 conservan todos sus bytes**. Un segundo agente verificó estáticamente la cuota, el plazo, las opciones y los hashes de las ocho ondas, sin cargar modelos; su revisión queda en `resource-review-v1/review-rms-v2.json` (`4f391484d8af85194236b33eb93a62d402a9cd82a0b1f2fd636126bb8a7d2dc0`).

| Artefacto v2 | SHA-256 |
|---|---|
| Adaptador y snapshot | `a79904f557b5ec612eb8bc54d291f05979d17c8130be88bcc9da2b7d973c501f` |
| Plan previo | `c3c3cb8b1b97c80ebbf43c768ac0a642813098c21af25ecfa6495330931f346e` |
| Manifiesto de audio reutilizado | `0803e817d5882b70326a165f13808d8bd76a825a78cd621861433accacf32831` |
| Protocolo de evaluación | `93e21ecda689c54f4921359e8c5179507af24a352e48977230995de446266fc7` |

El plan está en `build/generation-next/rms-vad-asr/v2/`. Se ejecutó una sola vez, después de revisar sus hashes y coordinar el único proceso de inferencia. El siguiente comando es un registro del intento, no una indicación de repetirlo:

```sh
build/generation-bench/env/bin/python scripts/experiments/rms_vad_asr.py synthetic --output build/generation-next/rms-vad-asr/v2
```

El proceso completó la importación en 0,065 s y la construcción del modelo en 0,825 s; la ejecución supervisada duró 7,664 s. Alcanzó 2.149,516 MiB RSS y 2.122,815 MiB de huella física, por debajo de la cuota. Tras retornar `transcribe`, el adaptador falló al escribir `part-000.json`: las comparaciones de tiempos `numpy.float64` producen indicadores `numpy.bool`, que el escritor JSON anterior no aceptaba. La salida fue 1, sin señales del supervisor; el proceso quedó recogido y su PID dejó de existir. No hubo un freeze exitoso ni transcripciones de canciones. El diagnóstico queda en `v2/synthetic-failed-assessment.json`, SHA-256 `7c373bc39cfb7dec8ca360ac85b66fb862a2c8b521ef8967c2a6fdd1fa010d62`.

El valor `raw_segments_local` ya estaba completo dentro del JSON parcial conservado. Su lectura separada, sin reparar ni sobrescribir ese archivo, registra **un segmento y cinco palabras producidas sobre el segundo de silencio**. El conteo y hash del texto están en `v2-silence-observation.json`. Esto es una limitación observada en el control, no un WER de canto ni una prueba de exactitud.

## Corrección de escalares y control técnico v3

Se reprodujo el fallo sin modelo con tiempos NumPy y sus indicadores. La regresión ampliada incluye dataclasses anidadas, `float32`, `float64`, `int64`, booleanos NumPy y un tiempo obtenido con `nextafter` para comprobar igualdad exacta tras el JSON. El escritor convierte exclusivamente escalares NumPy mediante `item()` a tipos Python nativos, sin redondear, eliminar campos ni convertir objetos arbitrarios a texto. Conserva `allow_nan=False`: NaN e infinito se rechazan. La serialización se valida antes de crear el archivo, evitando una nueva evidencia truncada. El control pasó de rojo a verde; los ocho controles ligeros y Ruff pasan. El control de tipos anterior sólo había utilizado valores Python nativos y no cubría este caso NumPy real.

El plan v3 mantiene los mismos pesos, opciones, cuatro identidades, cortes, ocho WAV originales, reglas de evaluación, cuota de 4 GiB y plazo de 120 s. Los 28 archivos de v1 y los 19 de v2 conservan exactamente sus bytes. Un único control v3 se ejecutó tras la revisión del código y del plan; **terminó con salida 0 y freeze verificado**. El supervisor confirmó la recogida, la consulta del PID confirmó su ausencia y el Mac permaneció silenciado. No se ejecutó automáticamente ninguna canción.

| Control v3 | Resultado |
|---|---:|
| Tiempo supervisado | 7,621 s |
| Muestras de recursos | 144 |
| Máximo RSS observado | 2.166,531 MiB |
| Máxima huella física observada | 2.139,877 MiB |
| Palabras crudas / conservadas por producción sobre silencio | 5 / 5 |
| Transcripciones de canciones al terminar sólo este control | 0 de 16 |

| Artefacto v3 | SHA-256 |
|---|---|
| Adaptador y snapshot | `2b4b95d80638188c750d506dfbac68e5011d153a32aecc5b84026eefa8a8583a` |
| Plan previo | `0a9e4d81a2462977c8b21871f9cc3fe5451db48ead5d6cb853d2e902e6bf183c` |
| Manifiesto de audio reutilizado | `07b4c792c70fba8dba50d399a70edfed88c3ed31d93f4f168ffcbf59d84e0659` |
| Protocolo de evaluación | `9559e1e7a5c0ed654a115e4162387b8d0eab6e024b290336d4931260e8b139f8` |
| Control sintético congelado | `50e0f631ec8bac412a2fcd20b98208b3fb78248cf64766301b265dc100a0eebb` |

Las fases, recursos, predicción cruda y líneas de producción están en `build/generation-next/rms-vad-asr/v3/synthetic-control/`; `synthetic-assessment.json` comprueba hashes, campos booleanos JSON nativos, concordancia entre fragmento y predicción, cierre y conservación de los fallos anteriores. Haber completado este control permite coordinar la prueba de canciones, pero no resuelve la aparición de palabras sobre silencio ni acredita letras correctas.

## Validación global previa a leer referencias

Una revisión independiente detectó que el evaluador anterior comprobaba cada predicción después de abrir su referencia y no volvía a verificar todos los recursos y fragmentos. Por tanto, una alteración en una condición posterior podía descubrirse cuando ya se habían abierto referencias anteriores. La corrección realiza primero una validación global de la procedencia, los hashes de todas las salidas, el estado de los procesos y los fragmentos; sólo después permite leer la primera referencia.

Tres controles sintéticos reprodujeron el defecto —predicción posterior alterada, recursos alterados y fragmentos alterados— junto a un caso válido. Tras corregirlo pasan los cuatro, sin inferencia ni letras humanas. Se verificaron además 225 casos independientes de S/D/I, vacío, tiempo absoluto y conservación de denominadores. El código del evaluador tiene SHA-256 `770b41166c0c231efa9a006283315f602f2523245a96a1e5dfc779748dd2d537`.

El protocolo anterior permanece conservado. Para el cierre se utilizó `v3/evaluation-protocol-preflight-v2.json`, SHA-256 `ed7101b40e749f79c335fd63679a5f5411041c273ba06573a1e5e8c8547b74d3`. Sólo cambian fecha y hash de implementación frente al protocolo original: las referencias, métricas, audio y condiciones son idénticos. Esta revisión no cambió el adaptador ASR, su plan ni la transcripción que estaba en marcha.


## Cohorte v3 completada y recursos medidos

Las dieciséis condiciones terminaron con salida 0, recogida confirmada y ausencia posterior de todos sus PID. Se conservaron los fragmentos, predicciones crudas y filtradas, recursos y fases de cada condición antes del freeze. La suma de tiempos supervisados fue **880,419 s (14 min 40 s)**, sin contar los pequeños intervalos del controlador. El máximo observado fue **2.332,797 MiB RSS** y **2.289,284 MiB de huella física**, bajo la cuota de 4.096 MiB. Hubo 16.657 muestras, con intervalo mediano de 52,926 ms y máximo de 61,658 ms; son máximos muestreados, no una garantía sobre picos entre muestras.

Cada condición tenía un proceso nuevo y plazo de 600 s. El coste final fue menor que la estimación previa de 20–30 minutos, pero los cortes RMS no aceleran necesariamente el reconocimiento: Northern Star pasó de aproximadamente 49 a 104 s sobre la mezcla. El resultado corresponde a CPU en hardware real y audio guardado, no a una medición de latencia de micrófono.

| Grabación | mix-native (s) | mix-rms (s) | vocals-native (s) | vocals-rms (s) |
|---|---:|---:|---:|---:|
| Amorfoda | 46,283 | 51,251 | 46,370 | 46,348 |
| 11 y 6 | 60,292 | 86,407 | 68,045 | 93,456 |
| Mr. Fancy Pants | 20,102 | 21,782 | 20,160 | 22,026 |
| Northern Star | 48,530 | 103,918 | 43,179 | 102,270 |

Los brazos RMS contienen respectivamente 7, 14, 3 y 18 fragmentos por fuente; cada brazo nativo entrega la onda completa a la segmentación interna del reconocedor. `cohort-assessment.json` conserva recursos, hashes, recogida y silencio del Mac.

## Resultados de letras y tiempos

La tabla muestra las dieciséis condiciones sin selección. WER y S/D/I corresponden a `product_lines`; WER crudo muestra por separado el efecto del filtro. La cobertura es la fracción de palabras de referencia que coinciden léxicamente en la alineación del medidor; p50/p90 son errores absolutos de inicio sólo para esas coincidencias. Son tiempos emitidos por ASR sobre el reloj original, **no una alineación forzada final de la letra**.

| Grabación | Brazo | S/D/I | WER producto (%) | WER crudo (%) | Cobertura exacta (%) | p50/p90 (ms) |
|---|---|---:|---:|---:|---:|---:|
| Amorfoda | mix-native | 73/15/11 | 34.138 | 34.138 | 69.655 | 130/262 |
| Amorfoda | mix-rms | 81/13/1 | 32.759 | 32.759 | 67.586 | 119/235 |
| Amorfoda | vocals-native | 84/8/3 | 32.759 | 32.759 | 68.276 | 121/235 |
| Amorfoda | vocals-rms | 75/10/1 | 29.655 | 29.655 | 70.690 | 121/248 |
| 11 y 6 | mix-native | 8/0/6 | 8.642 | 10.494 | 95.062 | 159/1098 |
| 11 y 6 | mix-rms | 11/1/10 | 13.580 | 14.198 | 92.593 | 147/672 |
| 11 y 6 | vocals-native | 8/0/6 | 8.642 | 10.494 | 95.062 | 158/1153 |
| 11 y 6 | vocals-rms | 8/1/12 | 12.963 | 12.963 | 94.444 | 147/683 |
| Mr. Fancy Pants | mix-native | 6/107/0 | 53.555 | 53.555 | 46.445 | 69/382 |
| Mr. Fancy Pants | mix-rms | 10/9/0 | 9.005 | 9.005 | 90.995 | 44/262 |
| Mr. Fancy Pants | vocals-native | 5/107/0 | 53.081 | 53.081 | 46.919 | 66/383 |
| Mr. Fancy Pants | vocals-rms | 6/8/0 | 6.635 | 6.635 | 93.365 | 47/227 |
| Northern Star | mix-native | 9/1/4 | 7.865 | 7.865 | 94.382 | 156/678 |
| Northern Star | mix-rms | 9/2/1 | 6.742 | 6.742 | 93.820 | 95/264 |
| Northern Star | vocals-native | 8/2/2 | 6.742 | 6.742 | 94.382 | 154/696 |
| Northern Star | vocals-rms | 5/2/0 | 3.933 | 3.933 | 96.067 | 98/275 |

Hay 841 palabras de referencia en las cuatro grabaciones: 290 de Amorfoda, 162 de 11 y 6, 211 de Mr. Fancy Pants y 178 de Northern Star. La mayor mejora primaria procede de recuperar omisiones en Mr. Fancy Pants (107 → 9); Amorfoda continúa con alrededor de un tercio de errores. Ninguna condición alcanza WER ≤ 1 %; sólo Northern Star/vocals-rms llega a WER ≤ 5 % (3,933 %). No hay nuevos mapas ni aprobaciones de los cinco controles musicales atribuibles a este ensayo.

| Brazo | Medidas / cohorte | S/D/I producto | WER agrupado producto (%) | Mediana producto (%) | WER agrupado crudo (%) | Mediana cruda (%) |
|---|---:|---:|---:|---:|---:|---:|
| mix-native | 4/40 | 96/123/21 | 28.537 | 21.390 | 28.894 | 22.316 |
| mix-rms | 4/40 | 111/25/12 | 17.598 | 11.292 | 17.717 | 11.601 |
| vocals-native | 4/40 | 105/117/11 | 27.705 | 20.700 | 28.062 | 21.626 |
| vocals-rms | 4/40 | 94/21/13 | 15.220 | 9.799 | 15.220 | 9.799 |

El primario reduce el WER agrupado un **38,33 % relativo**, y la mediana de 21,390 % a 11,292 %. Mejoran tres canciones y empeora una. El criterio de ampliación quedó firmado antes de abrir referencias en `expansion-decision-prior-to-evaluation.json` (`12959c5b3d07da26a080496155f76aa841b8390a5e2426c5ea2d146b9ee862cd`): cuatro parejas completas, reducción relativa agrupada ≥ 10 %, mediana menor, al menos tres sin empeorar y dos mejores, y ningún retroceso mayor de 2 puntos. Se cumplen todos salvo el último: en **11 y 6**, los errores pasan de **14/162 a 22/162**, un retroceso de **4,938 puntos**. La decisión es **no ampliar esta variante a las otras 36 identidades**, sin cambiar umbrales ni escoger vocals-rms retrospectivamente como nuevo primario.

El p90 del primario mejora en las cuatro canciones (262→235, 1.098→672, 382→262 y 678→264 ms), pero la cobertura exacta baja en tres de ellas; sólo aumenta en Mr. Fancy Pants. Por eso esa mejora temporal no demuestra por sí sola una sincronización de letra más completa. Las métricas tampoco son una comparación directa con la base corroborada del producto, que incorpora otras fuentes y decisiones: aquí se mide únicamente la salida acústica de Turbo con o sin cortes.

## Exportación, auditoría y alcance

El [CSV completo](generacion-rms-asr-2026-11-21.csv) conserva **320 filas**: 40 identidades × 4 brazos × 2 vistas. Hay 32 filas medidas y 288 ausentes, con métricas vacías, correspondientes a 144 condiciones fuera del piloto. Las ausentes no cuentan como éxito ni como WER cero. La copia en documentación es idéntica byte a byte al CSV congelado; el JSON conserva además las parejas temporales y estadísticas sin redondear.

La auditoría independiente comprobó 124 artefactos, identidades congeladas, recursos, todos los campos numéricos del CSV, identidades S/D/I/C y conciliación de percentiles temporales. No ejecutó otro reconocimiento ni una nueva alineación contra referencias: su alcance es procedencia y concordancia del export. El protocolo y la validación global precedieron a la lectura de referencias; los resultados no se utilizaron para modificar generación o parámetros.

| Evidencia v3 | SHA-256 |
|---|---|
| Freeze de generación | `c88bf5aa82893d41a018a88e65f03db8bd6182a092da3f51df79f9f17a253e12` |
| Entradas congeladas de evaluación | `65a53d13f2ea25e97704db7a33e73f8b60cbb5efc27b5e0485fb0d7de39f8975` |
| Evaluación JSON | `10d2c2c5f74ca1019a01c49945ee256953fcc3ceb4eeb48a5a0dda6432390f67` |
| CSV, original y copia documental | `4d7ea7a0e34528142ea495c3932356062064fb1f8ebed3815ca32f9cd3d7c948` |
| Auditoría independiente del export | `4d30cfa9990d3280dc239fd8f800ec01f26861ac03891cc064a46e3c20896fea` |
| Recursos y cierre de cohorte | `2c853796ef5444718381d73eeb7ebe5335b415992415584e58e33e1fb72ec02f` |

La fuente de producción usada por las dieciséis condiciones está preservada con SHA-256 `42914898eb0180da3fe2d59d121295a629632e18fc000aecc4d37f4a09623333`. La guardia de silencio posterior (`551247c`) no forma parte de estas salidas; este plan histórico no se vuelve a ejecutar sobre la fuente modificada. Permanecen intactos planes, audios, predicciones, fallos previos y evaluación. Los resultados justifican conservar la segmentación como hipótesis investigada, pero no integrarla como solución general de descarga fiable.
