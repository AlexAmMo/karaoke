# Heart: modo texto evaluado, sin ampliación

Activar únicamente `without_timestamps=True` redujo el WER agrupado de producto del **36,980 % al 22,473 %** frente al Heart anterior. La mejora es parcial: Northern Star empeoró 3,933 puntos, por encima de los 2 permitidos. **No se amplía ni se promueve esta variante**; tampoco supera el criterio frente a Turbo, aunque mejore su WER agrupado. Ninguna de las cuatro canciones alcanza WER ≤ 5 %.

La preparación inspeccionó código y metadatos sin modelos. Después se ejecutaron un control sintético y cuatro canciones completas, se congelaron todas las salidas y se evaluaron por separado. Las fuentes, resultados anteriores y umbrales permanecieron intactos. Los hechos y el protocolo previo se conservan a continuación; los resultados auditados cierran esta nota, que continúa [la investigación de conversión CPU](research-heart-cpu-2026-11-21.md).

## Hechos contrastados

Heartlib `164788308875289016d2f7ab46dba7f77a649cf8` fija **Transformers 4.57.0**. Su cargador crea `AutomaticSpeechRecognitionPipeline` con `chunk_length_s=30` y `batch_size=16`; el ejemplo utiliza CUDA/FP16, beam dos y no pide `return_timestamps`. El checkpoint `ee842de9aeec454236badef2205dea47a1fd8410` declara `return_timestamps=false`, `no_timestamps_token_id=50363` y tarea de transcripción. [Dependencias oficiales](https://github.com/HeartMuLa/heartlib/blob/164788308875289016d2f7ab46dba7f77a649cf8/pyproject.toml) · [Pipeline](https://github.com/HeartMuLa/heartlib/blob/164788308875289016d2f7ab46dba7f77a649cf8/src/heartlib/pipelines/lyrics_transcription.py) · [Ejemplo](https://github.com/HeartMuLa/heartlib/blob/164788308875289016d2f7ab46dba7f77a649cf8/examples/run_lyrics_transcription.py) · [Configuración original](https://huggingface.co/HeartMuLa/HeartTranscriptor-oss/resolve/ee842de9aeec454236badef2205dea47a1fd8410/generation_config.json)

En esa versión de Transformers, las ventanas de hasta treinta segundos conservan `return_timestamps=false`; `_retrieve_init_tokens` añade `<|notimestamps|>`. La regla que exige timestamps para entradas largas no convierte estas ventanas separadas en una única entrada larga. La configuración observada acredita el modo solicitado por el ejemplo; **no acredita cómo se entrenó el modelo**. [Generación Whisper fijada](https://github.com/huggingface/transformers/blob/v4.57.0/src/transformers/models/whisper/generation_whisper.py)

| Aspecto | Ejemplo oficial Heart | Ensayo local `heart-asr/v2` |
|---|---|---|
| Solicitud de tokens temporales | `return_timestamps=false`; prefijo con `<|notimestamps|>` | `without_timestamps` omitido; `WhisperModel.transcribe` usa `False` |
| Ventanas | 30 s; stride predeterminado de 5 s a cada lado, avance nominal de 20 s | Características de 30 s; avance calculado desde tokens/última palabra |
| Unión | `_decode_asr` resuelve secuencias comunes entre ventanas | Segmentación de faster-whisper y filtrado existente de Karaoke |
| Tiempos de palabra | El ejemplo no los solicita | `word_timestamps=True`, atención/DTW |

El stride de cinco segundos deriva del valor predeterminado `chunk_length_s / 6`; el avance es `30−5−5`. En el recorrido sin timestamps, el tokenizer oficial une las secuencias solapadas mediante `_find_longest_common_sequence`. Esto tampoco equivale a concatenar fragmentos independientes. [Preprocesado y postprocesado oficiales](https://github.com/huggingface/transformers/blob/v4.57.0/src/transformers/pipelines/automatic_speech_recognition.py) · [Unión del tokenizer](https://github.com/huggingface/transformers/blob/v4.57.0/src/transformers/models/whisper/tokenization_whisper.py)

En faster-whisper 1.2.1, `without_timestamps` y `word_timestamps` son opciones distintas. La primera añade el token al prefijo; la segunda solicita alineación. Además, cuando no hay un único timestamp final, la alineación puede mover `seek` al final de la última palabra. **Activar `without_timestamps=True` manteniendo los tiempos de palabra conserva ese avance adaptativo**: no restablece el stride ni la unión oficial. Tampoco debe confundirse el valor predeterminado `True` del pipeline *batched* con el `False` de `WhisperModel.transcribe`, que fue el método usado. [Implementación fijada](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py)

Un control sin runtimes ejecutó únicamente las funciones de construcción de argumentos extraídas por AST, con objetos Python simulados. Para español obtuvo prefijo oficial `[50258,50262,50359,50363]`, prefijo local anterior `[50258,50262,50359]` y el mismo prefijo oficial al activar la opción nueva. La fuente faster-whisper descargada coincide por hash con la instalada. Esto comprueba la diferencia de argumentos; no ejecuta la red ni mide su efecto.

## Protocolo previo conservado

**Hipótesis fijada antes del ensayo:** solicitar el modo sin timestamps reduce errores de letra del Heart convertido frente al modo local anterior. No está demostrado que los errores provengan del prefijo: también podrían influir la cuantización, los cortes, la alineación o el propio reconocedor.

El protocolo fijó añadir únicamente `without_timestamps=True` a los parámetros congelados de `heart-asr/v2`: mismo binario, cuatro WAV completos, idioma, semilla 113, beam dos, `best_of=1`, temperaturas, umbrales, máximo 256 tokens, CPU/dos hilos, tiempos por palabra y filtrado. No se cambiaron a la vez stride, unión ni alineador. Es una sola variable de configuración, con posibles efectos posteriores sobre segmentos y avance.

El protocolo se congeló antes de inferir. Se conservaron los argumentos efectivos, tokens de salida, segmentos, `seek` y tiempos que registra el adaptador, además de las salidas crudas y de producto y los recursos. El prefijo se comprobó con el control estático anterior; no se afirma que se capture cada prompt real ni se exige esa telemetría adicional. Las cuatro predicciones se congelaron antes de evaluar con las mismas referencias; no se escogió un brazo diferente por canción. Se mantuvieron 40 como denominador y 36 ausencias fuera del piloto.

Para comprobar la hipótesis se fijó aplicar frente a Heart v2 las mismas reglas de mejora ya declaradas: cuatro pares completos, reducción relativa de WER agrupado de producto de al menos 10 %, menor mediana, tres canciones sin empeorar, al menos dos mejores y ningún aumento individual superior a 0,02. El WER crudo y sus inserciones/omisiones se reportan por separado. **Para ampliar o promover la cadena se exigieron esas reglas frente a Turbo**, según `expansion-decision-before-asr.json`; mejorar sólo frente al Heart anterior no basta. El protocolo excluía ajustar estos parámetros o umbrales a las referencias después del contraste.

No se hizo otra descarga ni conversión. Se mantuvieron 4 GiB y 900 segundos por canción, un proceso a la vez, con interrupción y recogida ante fallo. Los cuatro procesos anteriores sumaron unos **348 segundos**, referencia de coste sin garantía para el nuevo avance. Los tiempos de palabra podrían degradarse, repetirse fragmentos o cambiar el número de ventanas; por eso mejorar WER no acreditaría sincronización ni notas fiables.

Fuentes y controles: `build/generation-next/heart-decoding-research/sources.json` y `static-controls.json` — SHA-256 del control **`4210122bc8214511921ec059ed5829e24da99067294787f1984318dd7c983099`**. Baseline local: plan `aa46ae5163621074b83afc8931556771e104098c196dc4c124225d8a1907c28f`, freeze `c80a5daa74cfe43c64389175ed768c1b8949fa90f99a9506b0c5155a4452f6bd`.

## Adaptador y protocolo del ensayo

El [adaptador separado](../../scripts/experiments/heart_asr_no_timestamps.py) reutiliza el runner anterior sin modificar su archivo ni los resultados congelados. Verifica su SHA-256 antes de importarlo, registra ambas fuentes y hace que cada proceso hijo ejecute la variante. Las doce pruebas ligeras pasan; el control con audio real y reconocedor simulado pasa también en el entorno Heart, sin cargar modelos. El evaluador anterior se reutiliza intacto.

El plan `build/generation-next/heart-asr/no-timestamps-v1/plan.json` tiene SHA-256 `a795614b0a1a9fb844ed32228c77916ea9cf6d20da3776d37b2868cfe71825c1`; el protocolo de evaluación, `15adce5ad08b408013654c7aa6a018c1468e655ea68e54439cd4673e41599f29`. La revisión del plan confirma que sólo cambian la opción, las fuentes que identifican el wrapper y los metadatos de propuesta/fecha. Modelo, conversión, cuatro audios, versión de Python, dependencias, semilla y límites coinciden con v2.

Antes de inferir se conservaron dos reglas: ampliación frente a Turbo (`b49c8e3c75d150f9e786f05bd8b7fc792956df6660200ebdd67900e91b31015a`) y contraste de la hipótesis frente al Heart anterior (`4cd426ab037a771f0d55815b6074fe3fbb9319efeb2422455663e0dcad1d6e36`). Ambas exigen todos los pares y los umbrales descritos arriba. El piloto pertenece al conjunto de desarrollo ya conocido, no a una evaluación inédita.


## Control y cohorte terminados

El único control sintético, dos segundos de tono no nulo, terminó en **14,489 s**, con salida 0, recogida confirmada y PID ausente. Se verificaron el audio exacto, el comando del hijo y los argumentos efectivos `without_timestamps=True` y `word_timestamps=True`. Produjo **una palabra cruda y una conservada por el producto** sobre una señal sin habla: sigue siendo una alucinación del control, no una prueba de precisión. Su freeze es `d2d6d2d8b6fb48a0e63b440e75213fa53280bb796e7baadb1c7f6d9afa147091`; la auditoría, `8cf2ca87960582049d44db05c37b8503d87a54fae46f4f61e40d92998f744b43`.

Después terminaron las cuatro canciones completas, secuenciales, con salida 0, sin cortes ni reintentos. Todos los procesos quedaron recogidos y sus PID ausentes. El Mac M4 permaneció silenciado; fue inferencia CPU sobre audio guardado. Las referencias no se abrieron durante generación ni durante esta auditoría técnica.

| Grabación | Tiempo (s) | Máximo RSS observado (MiB) | Máxima huella física (MiB) |
|---|---:|---:|---:|
| Amorfoda | 64.307 | 1697.953 | 1654.986 |
| 11 y 6 | 79.888 | 1691.281 | 1648.314 |
| Mr. Fancy Pants | 56.725 | 1629.484 | 1586.596 |
| Northern Star | 106.252 | 1667.109 | 1624.127 |

La suma supervisada fue **307,172 s (5 min 7 s)**, frente a 348,312 s del Heart anterior; no es una prueba alternada de rendimiento. Se tomaron 5.782 muestras, con intervalo mediano de 52,758 ms y máximo de 60,454 ms; no garantizan capturar picos entre muestras. Se conservaron los mismos límites de 4 GiB/900 s.

El freeze de cuatro predicciones es `4d2855920557bf0e4f95fce73c38d546a8c88dc1a8d8b496ff3ca9c011af0e51`. `cohort-assessment.json`, SHA-256 `70a9304f5cdc014b9d978ba5331a43ed7cfddb32a7575161ea8414ad9969805b`, verifica 40 registros, identidad y reloj, correspondencia crudo/producto, argumentos efectivos, procesos y silencio del Mac. La evaluación de precisión se realiza por separado después de este cierre; el éxito técnico no confirma la hipótesis de letras.


## Evaluación auditada: mejora parcial, sin ampliación

Se evaluaron las cuatro predicciones completas después del freeze, con el medidor y las dos reglas predeclaradas intactos. La hipótesis recibe una **señal parcial favorable**, pero **no supera ninguno de los dos criterios de aceptación**: el WER agrupado baja, mientras persisten retrocesos por canción mayores de lo permitido. No se ampliará esta variante a las otras 36 grabaciones ni se promoverá como solución fiable de descarga.

Todas las cifras WER son porcentajes. Las tres primeras columnas de WER comparan el texto conservado por el producto; la vista cruda del modo texto se muestra aparte, sin quitar repeticiones. S/D/I, cobertura y tiempos corresponden al producto del nuevo modo. La cobertura es la fracción de palabras de referencia coincidentes; p50/p90 mide sólo sus errores absolutos de inicio, sin corregir desplazamientos.

| Grabación | Turbo WER | Heart anterior WER | Modo texto WER | Crudo WER | S/D/I | Cobertura (%) | p50/p90 (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Amorfoda | 32.759 | 60.345 | 31.034 | 34.828 | 44/7/39 | 82.414 | 60/185 |
| 11 y 6 | 8.642 | 41.975 | 19.136 | 22.222 | 6/1/24 | 95.679 | 136/849 |
| Mr. Fancy Pants | 53.081 | 13.744 | 10.427 | 9.953 | 12/5/5 | 91.943 | 88/164 |
| Northern Star | 6.742 | 21.910 | 25.843 | 44.944 | 12/1/33 | 92.697 | 95/645 |

El nuevo producto suma **74 sustituciones, 14 eliminaciones y 101 inserciones: 189 errores/841 palabras**, con 753 coincidencias. Su WER agrupado es **22,473 %** y la mediana **22,489 %**. La vista cruda conserva **77/7/154 errores S/D/I**, 757 coincidencias y WER agrupado **28,300 %**; el filtro no convierte esa salida en letra casi perfecta. El menor WER productivo por canción sigue siendo 10,427 %: ninguna alcanza el 5 % ni el 1 %. No se han generado nuevos mapas.

**Frente a Turbo**, el WER agrupado mejora de 27,705 % a 22,473 % (**18,884 % relativo**), pero la mediana empeora de 20,700 % a 22,489 %. Mejoran Amorfoda y Mr. Fancy Pants; empeoran 11 y 6 (**+10,494 puntos**) y Northern Star (**+19,101 puntos**). Se cumplen tres de seis condiciones: cuatro parejas, reducción agrupada ≥ 10 % y dos mejoras. Fallan mediana inferior, al menos tres canciones sin empeorar y máximo retroceso de 2 puntos. La vista cruda agrupada también debe conservarse: queda ligeramente peor que Turbo (28,300 % frente a 28,062 %).

**Frente al Heart anterior**, los errores productivos bajan de **311 a 189 sobre 841**: WER 36,980 % → 22,473 %, una reducción relativa de **39,228 %**; la mediana baja de 31,943 % a 22,489 %. Mejoran tres canciones, pero Northern Star empeora **7/178 = 3,933 puntos**, de 21,910 % a 25,843 %. Se cumplen cinco de seis condiciones del contraste interno; vuelve a fallar el máximo de 2 puntos. La vista cruda agrupada baja de 55,886 % a 28,300 %. Mejorar frente a ese intento anterior no basta para ampliar la cadena.

El p90 de inicio mejora frente a Turbo en las cuatro canciones, pero Northern Star tiene menos coincidencias léxicas (94,382 % → 92,697 %). Estos tiempos ASR no son la alineación forzada final ni límites musicales de notas. Son **4/40 grabaciones de desarrollo por cadena**, no un conjunto reservado ni una demostración sobre cualquier canción. El único cambio solicitado fue el modo de timestamps; los efectos posteriores sobre recorrido y segmentos no permiten atribuir por separado todos los errores restantes.

El [CSV completo](generacion-heart-sin-timestamps-2026-11-21.csv) conserva exactamente los **12.996 bytes y 161 finales CRLF** del original: 160 filas, 16 medidas y 144 ausentes. Las ausentes tienen métricas vacías y no cuentan como éxito ni WER cero. La auditoría del export reconcilió métricas, tiempos y recursos; el comparador interno independiente verificó su JSON y CSV de 80 filas (8 medidas y 72 ausentes). No reejecutaron modelos ni cambiaron referencias o umbrales.

| Evidencia | SHA-256 |
|---|---|
| Evaluación frente a Turbo | `0158d3852014992bddbb8da64926b6b672cca67785a388b211e567913e624846` |
| CSV original y copia documental | `d82cc71465686f588645a2e94ae416b933bb325c50983eb852ac5f1f1c0e3009` |
| Auditoría del export | `29cfa57dad10535b1a7226c3af2a64fd3cbb724fee0def666e5709ffd256d141` |
| Contraste interno frente a Heart anterior | `8299f5bdb86701ef99e34bfad4c2decae3524241b89c304f5ca4c60cd2c5120c` |
| Auditoría del contraste interno | `ddcbb32279c33db282f16dad082976a9c1522f4bd3c72fd13b18cb80165137ad` |
