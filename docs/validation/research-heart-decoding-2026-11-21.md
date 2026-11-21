# Heart: diferencia comprobada en el modo de decodificación

Hay una diferencia concreta que permite formular un ensayo adicional: **el ejemplo oficial solicita texto sin timestamps; nuestro ensayo faster-whisper heredó la generación con timestamps**. Cambiar únicamente `without_timestamps=True` es una hipótesis sustentada, todavía sin resultado. No demostraría que reproducimos el pipeline oficial ni que esa diferencia explique el empeoramiento observado en tres de cuatro canciones.

Se han inspeccionado código y metadatos, sin modelos, nuevas transcripciones ni modificaciones de producción o archivos congelados. Esta nota continúa [la investigación de conversión CPU](research-heart-cpu-2026-11-21.md).

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

## Única hipótesis propuesta

**Hipótesis:** solicitar el modo sin timestamps reduce errores de letra del Heart convertido frente al modo local anterior. No está demostrado que los errores provengan del prefijo: también podrían influir la cuantización, los cortes, la alineación o el propio reconocedor.

Si se decide probarla, el nuevo brazo sólo añadirá `without_timestamps=True` a los parámetros congelados de `heart-asr/v2`: mismo binario, cuatro WAV completos, idioma, semilla 113, beam dos, `best_of=1`, temperaturas, umbrales, máximo 256 tokens, CPU/dos hilos, tiempos por palabra y filtrado. No se cambiarán a la vez stride, unión ni alineador. Es una sola variable de configuración, con posibles efectos posteriores sobre segmentos y avance.

El protocolo debe congelarse antes de inferir. Se conservarán los argumentos efectivos, tokens de salida, segmentos, `seek` y tiempos que registra el adaptador, además de las salidas crudas y de producto y los recursos. El prefijo se comprobó con el control estático anterior; no se afirma que se capture cada prompt real ni se exige esa telemetría adicional. Las cuatro predicciones deben congelarse antes de evaluar con las mismas referencias; no se escogerá un brazo diferente por canción. Se mantendrán 40 como denominador y 36 ausencias fuera del piloto.

Para comprobar la hipótesis se propone aplicar frente a Heart v2 las mismas reglas de mejora ya declaradas: cuatro pares completos, reducción relativa de WER agrupado de producto de al menos 10 %, menor mediana, tres canciones sin empeorar, al menos dos mejores y ningún aumento individual superior a 0,02. El WER crudo y sus inserciones/omisiones se reportarán por separado. **Para ampliar o promover la cadena seguirán exigiéndose esas reglas frente a Turbo**, según `expansion-decision-before-asr.json`; mejorar sólo frente al Heart anterior no basta. Si falla el contraste predeclarado, no se ajustarán estos parámetros o umbrales a las referencias.

No hacen falta otra descarga ni conversión. Se mantendrían 4 GiB y 900 segundos por canción, un proceso a la vez, con interrupción y recogida ante fallo. Los cuatro procesos anteriores sumaron unos **348 segundos**, referencia de coste sin garantía para el nuevo avance. Los tiempos de palabra podrían degradarse, repetirse fragmentos o cambiar el número de ventanas; por eso mejorar WER no acreditaría sincronización ni notas fiables. Este ensayo aún no está implementado ni ejecutado.

Fuentes y controles: `build/generation-next/heart-decoding-research/sources.json` y `static-controls.json` — SHA-256 del control **`4210122bc8214511921ec059ed5829e24da99067294787f1984318dd7c983099`**. Baseline local: plan `aa46ae5163621074b83afc8931556771e104098c196dc4c124225d8a1907c28f`, freeze `c80a5daa74cfe43c64389175ed768c1b8949fa90f99a9506b0c5155a4452f6bd`.
