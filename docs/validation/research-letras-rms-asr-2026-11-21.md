# Comparación de letras con cortes RMS: adaptador preparado

Está preparado `scripts/experiments/rms_vad_asr.py` y están congelados los ocho audios necesarios para comparar cuatro canciones completas con cuatro condiciones. **No se ha cargado Whisper, ejecutado ASR ni consultado letras de referencia en esta fase.** El presupuesto de 2 GiB aún debe comprobarse con los pesos reales; no se declara que la carga quepa en él.

El plan `build/generation-next/rms-vad-asr/v1/plan.json` fija como comparación primaria **mix-rms frente a mix-native**. Se conservarán también vocals-native y vocals-rms, completos y sin escoger un brazo diferente por canción. Las cuatro identidades son Amorfoda, 11 y 6, Mr. Fancy Pants y Northern Star; son el piloto de desarrollo anterior, no un conjunto reservado. El plan enlaza los cortes previamente congelados para las cuarenta identidades, pero sólo prepara este factorial de dieciséis transcripciones. Una salida faltante o truncada seguirá siendo un fallo.

## Pesos, función de producción y reloj

Se ha localizado el Turbo real en la caché local, revisión `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf` de `mobiuslabsgmbh/faster-whisper-large-v3-turbo`. Su `model.bin` ocupa 1.617.884.929 bytes y tiene SHA-256 `e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da`. El plan guarda también los hashes de configuración, preprocesador, tokenizer y vocabulario. La carpeta antigua `build/generation-bench/model` corresponde a Small y no se utiliza. No se descargaron otros pesos.

Cada condición reutilizará `generation_worker.transcribe` con sus opciones exactas: CPU int8, tres hilos, beam cinco, tiempos de palabra, idioma fijo, VAD desactivado y condicionamiento por texto anterior desactivado. Se pasa un envoltorio del modelo que registra cada segmento crudo antes del filtro de producción. Así se conservan puntuación, palabras de duración no positiva, repeticiones y resultados que crucen una frontera; las líneas filtradas de la app se guardan por separado.

La mezcla se decodifica con el mismo comando FFmpeg de `split_vocals`: primer flujo de audio, 44.100 Hz, dos canales y WAV FLOAT. La media float32 entre canales y `scipy.signal.resample_poly` son los mismos de `transcribe`; se preparan una sola vez por fuente y ambos brazos leen ese mismo WAV mono de 16 kHz. El brazo nativo recibe toda la onda. El RMS utiliza los cortes de voz ya fijados y transforma cada frontera mediante `round(muestra × 16000 / 44100)`. Se registra cualquier recorte final. Los tiempos reconocidos vuelven al reloj absoluto sumando la muestra inicial dividida por 16.000, sin desplazar ni estirar el audio.

Este detalle afecta al piloto: el lector directo de MP3 de SoundFile informa 79,601882 s para Mr. Fancy Pants, mientras que el reloj decodificado que produjo su voz es de aproximadamente 79,5167 s. No se mezclan ambos relojes: se utiliza FFmpeg como en producción y se comprueba la longitud resultante. Las ocho ondas preparadas coinciden exactamente entre mezcla y voces:

| Grabación | Muestras por fuente a 16 kHz | Fuentes |
|---|---:|---:|
| Amorfoda | 2.829.677 | 2 |
| 11 y 6 | 4.241.450 | 2 |
| Mr. Fancy Pants | 1.272.268 | 2 |
| Northern Star | 3.042.764 | 2 |

La preparación procesa una fuente a la vez, antes del modelo, y rechaza entradas de más de 300 s, más de dos canales o más de 48 kHz. El piloto llegó a **299,5 MiB RSS** y terminó en **2,355 s**, incluida la decodificación de las cuatro mezclas. Es coste de preparación, no de reconocimiento. Los WAV y sus hashes quedan en `audio-frozen.json`.

## Controles y ejecución pendiente

Seis controles ligeros verifican el reloj entero compartido, la entrada nativa completa, la conservación de palabras que cruzan el corte, las repeticiones y duraciones no positivas, y la llamada real a producción con reconocedor simulado. Este último comprueba todos los argumentos y que la captura cruda precede al filtrado. Dos controles adicionales con audio sintético estéreo de 44.100 y 48.000 Hz comparan el remuestreo con la entrada recibida por esa función de producción: los resultados son idénticos byte a byte, incluidos extremos y longitud no divisible. No importan el reconocedor real ni Torch.

Un segundo agente revisó estáticamente la captura, la suma del tiempo absoluto, el redondeo compartido, el recorte final registrado y el requisito del control supervisado previo, sin identificar un defecto en esas rutas. No repitió los controles ni ejecutó ASR. Ruff y `git diff --check` pasan.

La ejecución futura crea un proceso nuevo por canción y condición. Reutiliza el supervisor probado de `yourmt3_notes.py` y la lectura `libproc` de `lead_vocals.py`, ambos firmados en el plan. Observa RSS y huella física cada 50 ms, corta al alcanzar 2 GiB o perder la telemetría, recoge el proceso y detiene la cohorte si hay fallo. Cada condición tiene un máximo de 600 s. Este muestreo no es un límite de asignación del sistema ni garantiza que el pico entre muestras no lo supere. Un fichero de pesos de 1,618 GB puede necesitar memoria adicional durante la conversión int8.

Antes de las dieciséis condiciones, `synthetic` deberá cargar esos mismos pesos en un proceso supervisado y recorrer la API con un segundo de silencio. Sólo si termina y queda recogido escribe `synthetic-frozen.json`; `execute` exige ese resultado de su mismo plan. Ese control comprobará carga/API, no la memoria máxima de una canción ni calidad de letra. **Ninguno de ambos comandos se ha ejecutado.** Deben coordinarse con el único proceso de inferencia del Mac.

Los **20–30 minutos** propuestos son una estimación basada en tiempos anteriores de Turbo de aproximadamente 70–100 s por grabación, con sobrecoste desconocido de carga y fragmentación. No son una medición de este ensayo. Los dieciséis topes individuales suman 160 minutos. No se cambiará el presupuesto después de ver una letra de referencia; cualquier nueva configuración necesitará otro plan y conservará la anterior.

```sh
# Ya completados sin modelos:
build/generation-bench/env/bin/python scripts/experiments/rms_vad_asr.py selftest
build/generation-bench/env/bin/python scripts/experiments/rms_vad_asr.py plan
build/generation-bench/env/bin/python scripts/experiments/rms_vad_asr.py prepare

# Fases posteriores, todavía pendientes de la coordinación del único modelo:
build/generation-bench/env/bin/python scripts/experiments/rms_vad_asr.py synthetic
build/generation-bench/env/bin/python scripts/experiments/rms_vad_asr.py execute
```

El directorio v1 es inmutable; para reproducir preparación se debe elegir un directorio nuevo mediante `--output`. La evaluación de letras se hará por separado después de congelar todas las salidas. Esta fase no implementa ni modifica el medidor.

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
