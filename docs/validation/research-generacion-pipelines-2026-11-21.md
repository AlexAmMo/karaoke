# Generación automática: implementaciones reutilizables, 21 de noviembre de 2026

La investigación encuentra dos ensayos nuevos con una justificación concreta: SwiftF0 0.3.0 para altura y segmentación de notas, y Qwen3-ASR 1.7B para reconocer palabras cantadas. No encuentra una implementación que demuestre mapas y letras casi perfectos para cualquier canción. La comprobación debe seguir usando las mismas 40 grabaciones completas y los cinco límites actuales, sin elegir parámetros después de mirar sus referencias. El estado previo está en [generación y retorno](generacion-youtube-y-retorno.md).

## Qué cambia respecto a lo ya probado

| Proyecto inspeccionado | Revisión del código | Hallazgo y uso posible |
|---|---|---|
| UltrastarCreatorTool | `b91cd382e2afc5fdb625f803819614cdcf118ebb` | Desde la revisión usada por Karaoke, `39d3eb5`, los servicios sólo cambian exportación de audio y cabeceras UltraStar. `game_notes.py`, `forced_alignment.py` y `pitch_detection.py` son idénticos. Actualizar esa dependencia no mejora el algoritmo. [Comparación primaria](https://github.com/retotito/UltrastarCreatorTool/compare/39d3eb5f9fb1e24220c4ca58888af8a88e11a38a...b91cd382e2afc5fdb625f803819614cdcf118ebb) |
| UltraSinger | `e94d94246042e48214286a0e144a4bd25832e60e` | Combina separación Demucs, Whisper/WhisperX y SwiftF0. Reconoce español, pero no publica evidencia de precisión casi perfecta en el corpus de Karaoke. Código MIT. [Código y licencia](https://github.com/rakuri255/UltraSinger/tree/e94d94246042e48214286a0e144a4bd25832e60e) |
| UltraStarKaraokeMaker | `40ee0f173cee66c2a71383555a79e11bbf71c011` | Alineación CTC global, rescates con voz separada, SwiftF0 y reglas explícitas para melismas. Código MIT. Las mejoras de su biblioteca son pistas para experimentar, no resultados trasladables a nuestras grabaciones. [Código y licencia](https://github.com/walterfr/UltraStarKaraokeMaker/tree/40ee0f173cee66c2a71383555a79e11bbf71c011) |
| AutoKaraoke | `3b7098f8a4847bc7d55238c6860a5f8b22cf5dc7` | Qwen ASR opcional, alineación por sílabas Qwen con contraste MMS y editor. Produce vídeo karaoke; no resuelve la altura para puntuar. Código GPL-3.0-or-later. [Código y licencia](https://github.com/GiacoBot/AutoKaraoke/tree/3b7098f8a4847bc7d55238c6860a5f8b22cf5dc7) |

## Letras españolas y segmentación del reconocimiento

Qwen3-ASR es un reconocedor distinto de Qwen3-ForcedAligner, ya ensayado para los tiempos. El modelo de reconocimiento admite español y canto, tiene pesos públicos y licencia Apache-2.0. Esto permite contrastar palabras obtenidas del audio con Whisper y con subtítulos manuales, conservando la comprobación de identidad temporal. No convierte el acuerdo entre reconocedores en una garantía de exactitud. [Modelo original y API](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)

La fuente primaria verificable es el informe técnico del equipo Qwen, enlazado desde su repositorio. Su sección 4.4, tabla 7, publica un WER del 14,60 % para Qwen3-ASR-1.7B en EntireSongs-en, canciones completas en inglés con acompañamiento. Es un conjunto interno y una medición de los autores, no este corpus; la tabla también incluye chino, pero no canciones españolas. Tampoco evalúa nuestra conversión GGUF ni nuestra fragmentación. Es una motivación para ensayar el reconocedor, no evidencia de precisión casi perfecta ni una predicción de su resultado en Karaoke. [Repositorio original](https://github.com/QwenLM/Qwen3-ASR) · [Informe técnico, sección 4.4](https://arxiv.org/html/2601.21337v1#S4.SS4)

**Corrección de procedencia.** Se retiraron las cifras y detalles atribuidos a MIREX 2026 que sólo se habían recuperado en `futuremirex.com`. No se pudo corroborar esa copia mediante un enlace desde los autores o el organizador: el wiki en `music-ir.org` no respondió y las páginas de los autores consultadas no enlazaban esos resultados. No se utiliza ese dominio como fuente oficial, ranking o evidencia comparativa. La consulta verificó las páginas de [Tomáš Sourada](https://ufal.mff.cuni.cz/tomas-sourada), [Jan Hajič jr.](https://ufal.mff.cuni.cz/jan-hajic-jr) y [PMCG](https://ufal.mff.cuni.cz/pmcg); su ausencia de enlaces no prueba que el trabajo no exista, pero impide sostener aquí las afirmaciones anteriores.

AutoKaraoke corta ventanas de 30 segundos buscando 0,3 segundos de menor energía en su último tercio, usa Qwen3-ASR-1.7B y alinea con Qwen3-ForcedAligner-0.6B. Es una alternativa concreta al corte fijo: evita dividir algunas palabras, aunque requiere medir si también omite entradas suaves. Su interfaz incluye edición humana y reconoce que la corrección por LLM es irregular. [ASR implementado](https://github.com/GiacoBot/AutoKaraoke/blob/3b7098f8a4847bc7d55238c6860a5f8b22cf5dc7/src/autokaraoke/asr.py) · [Flujo y limitaciones](https://github.com/GiacoBot/AutoKaraoke/blob/3b7098f8a4847bc7d55238c6860a5f8b22cf5dc7/README.md)

Para este Mac de 16 GiB, la vía GGUF evita descargar el conjunto PyTorch completo. CrispASR ofrece Qwen3 con ventanas de 30 segundos; procesar toda la canción de una vez incrementa fuertemente la memoria. La conversión `cstr` documenta una corrección del codificador de audio que evitó texto vacío o repetido en conversiones anteriores: hay que fijar revisión y hash de los pesos, no reutilizar un GGUF antiguo por su nombre. Esto es un ensayo separado: el modelo de alineación ya descargado no contiene el reconocedor. [CrispASR](https://github.com/CrispStrobe/CrispASR/blob/main/README.md) · [Conversión y advertencias del autor](https://huggingface.co/cstr/qwen3-asr-1.7b-GGUF)

## Alineación y melismas reutilizables

UltraStarKaraokeMaker alinea el texto completo con MMS CTC y comodines entre líneas. Conserva vocales sostenidas y recorta prefijos aislados sólo bajo condiciones de duración y hueco. Reutiliza emisiones y rescata líneas poco fiables con voz separada. Para español usa MMS; la vía wav2vec2 específica es sueca. Es una variante de decodificación distinta, aunque Karaoke ya usa un CTC especializado en canto: sustituirlo sin comparación no está justificado. [Alineador concreto](https://github.com/walterfr/UltraStarKaraokeMaker/blob/40ee0f173cee66c2a71383555a79e11bbf71c011/python-sidecar/pipeline/ctc_align.py)

Su constructor reparte la duración de sílabas según voz, divide melismas por cambios de altura y silencios y combina fragmentos pequeños. Puede inspirar un ensayo que conserve consonantes para mostrar la letra y puntúe las vocales. Las reglas están acopladas a su salida de alineación y deben probarse como un conjunto fijo, incluyendo notas repetidas y respiraciones. [Construcción de notas](https://github.com/walterfr/UltraStarKaraokeMaker/blob/40ee0f173cee66c2a71383555a79e11bbf71c011/python-sidecar/pipeline/build_song.py)

La evaluación por etapas de ese proyecto puede suministrar límites humanos de notas a SwiftF0 para aislar la altura. Es útil para diagnosticar, pero ese número no demuestra una generación autónoma de los límites. Nuestro ensayo entrega sólo la voz y la letra predicha al generador; la referencia se abre después de congelar los resultados. [Condiciones de evaluación del proyecto](https://github.com/walterfr/UltraStarKaraokeMaker/blob/40ee0f173cee66c2a71383555a79e11bbf71c011/eval/README.md)

## Ensayo mínimo de SwiftF0

SwiftF0 0.3.0 incluye un modelo ONNX de 14.386 parámetros y licencia MIT. Se inspeccionó `d1ba77fe5331310b778ebe126b6cb3656d41d24f`. La API entrega altura, confianza y nivel por cuadro de 16 ms. El segmentador busca límites globalmente y detecta repeticiones de la misma nota mediante caídas de nivel. Sigue siendo monofónico: puede seguir coros o instrumentos filtrados. [API y límites](https://github.com/lars76/swift-f0/blob/d1ba77fe5331310b778ebe126b6cb3656d41d24f/README.md) · [Implementación musical](https://github.com/lars76/swift-f0/blob/d1ba77fe5331310b778ebe126b6cb3656d41d24f/swift_f0/music.py)

La versión 0.3.0 mantiene los pesos de 0.2.0, cambia la segmentación y reduce la memoria para audios largos. El autor publica una mejora de notas del 4–7 % y F1 de altura de 0,778 a 0,781; son sus bancos y métricas. Esta información motiva probarlo, sin inferir que supere GAME en Karaoke. [Cambios versionados](https://github.com/lars76/swift-f0/blob/d1ba77fe5331310b778ebe126b6cb3656d41d24f/CHANGELOG.md)

El experimento usa las 40 voces ya separadas, filtradas por `generacion-muestra.json`, y los mapas base con los dos textos corregidos. Fija `threads=2`, `spin=False`, rango completo y `pitch_hold_ms=80`, sin ajuste sobre referencias. Produce dos mapas mediante `melody_compare.transform`: cambiar sólo alturas conservando el ritmo, o reconstruir eventos y melismas conservando las sílabas predichas. Guarda hashes de modelo, voces, base, eventos y mapas antes de medir. Evalúa WER ≤5 %, p90 de palabra ≤120 ms, clase ≥90 %, F1 de ataque ≥0,85 y precisión sobre tiempo pedido ≥90 %. Los eventos sin letra se miden únicamente como diagnóstico.

Código reproducible: [swift_notes.py](../../scripts/experiments/swift_notes.py). Salidas privadas nuevas: `build/generation-next/swift/`. No cambia dependencias ni el motor de producción. La comparación no usa el recorte por referencia de la admisión: ese recorte puede verificar una grabación conocida, pero no demuestra generación casi perfecta para una canción nueva.

### Resultado local del ensayo completo

Se generaron y congelaron las 40 grabaciones a las 17:42:09 UTC del 21 de noviembre. El Mac procesó toda la tanda en 40,23 segundos con dos hilos CPU; el máximo residente medido por `/usr/bin/time -l` fue 797.818.880 bytes, aproximadamente 761 MiB, y no hubo intercambios a disco. Se reutilizó el entorno de experimentos, con SwiftF0 0.3.0, NumPy 2.5.5 y ONNX Runtime 1.32.0. Los resultados y trazas ocupan aproximadamente 12 MiB. No se reprodujo audio.

| Tratamiento, 40 canciones | WER mediano | P90 de palabra mediano | Clase mediana | F1 de ataque mediano | Precisión del tiempo pedido mediana | Pasan cuatro / cinco |
|---|---:|---:|---:|---:|---:|---:|
| Base GAME con los dos textos corregidos | 6,72 % | 107 ms | 76,48 % | 0,668 | 50,26 % | 1 / 0 |
| SwiftF0 cambia sólo la altura | 6,72 % | 107 ms | 73,32 % | 0,635 | 49,90 % | 1 / 0 |
| SwiftF0 reconstruye eventos y melismas | 6,72 % | 117 ms | 59,33 % | 0,559 | 53,35 % | 0 / 0 |

Cambiar sólo la altura mejora la clase en seis canciones y la empeora en 34; mejora el F1 en siete, lo empeora en 31 y lo conserva en dos. Reconstruir eventos empeora la cobertura correcta de clase en las 40. La mediana de clase de esta reconstrucción queda en 60,62 % para inglés y 56,71 % para español. Los eventos acústicos antes de añadir sílabas tienen clase mediana de 60,18 % y F1 de 0,506: la diferencia no procede únicamente de cómo se adapta la letra.

El [evaluador común](../../scripts/experiments/evaluate_generation_candidate.py), ejecutado también con `--near-perfect`, verificó los hashes, evaluó 40 de 40 por variante, y no encontró mapas ausentes o inválidos. Ninguna variante supera los cinco controles ni el objetivo de investigación más estricto. Que la base sin recortes obtenga cero aprobaciones aquí es compatible con la admisión de «Amorfoda» en producción: esa admisión ajusta los intervalos contra una referencia independiente y luego vuelve a medir. Este ensayo mide predicciones autónomas sin esa ayuda.

Se conservan `frozen.json`, `metrics.csv`, `metrics-five.csv`, `metrics-five.json` y `common-evaluation/{baseline,pitch,events}/evaluation.json` en el directorio privado del ensayo. `run.json` fija hashes de los módulos y del modelo; `source-at-generation.py` conserva los bytes del adaptador usados antes de una corrección de serialización booleana del evaluador. Esa corrección no cambió las predicciones. Los formatos y comprobaciones estáticas del adaptador pasan. **No se propone sustituir GAME por SwiftF0 a partir de estos resultados.**

## Ensayo completo de Qwen3-ASR: las mismas 40 grabaciones

Se transcribieron completas las 40 mezclas originales del corpus fijado —20 españolas y 20 inglesas— con [qwen_lyrics.py](../../scripts/experiments/qwen_lyrics.py). El idioma procede de los metadatos del mapa base; no se proporcionó texto de referencia al reconocedor. Se utilizó `source_kind=mix`, no la voz separada. El piloto con voz separada no justificó ampliar esa variante a las 40 canciones.

Configuración fijada antes de evaluar: Qwen3-ASR 1.7B convertido a GGUF Q4_K, revisión `674df5d44b50a63e7102a18895ed20e3f91de301`; CrispASR 0.8.54 (`6221fbb7`), Metal sobre Apple M4, dos hilos CPU, ventanas consecutivas de **28 segundos**, solapamiento **0**, deduplicación LCS desactivada y máximo de 512 tokens por ventana. Se conservan las repeticiones de las letras. La generación se ejecutó secuencialmente en `build/generation-next/qwen/mix-full-v1`, sin cambiar parámetros después de consultar resultados. El conjunto sigue siendo el corpus de desarrollo, no una reserva independiente nunca observada.

Huellas SHA-256 de procedencia:

- Pesos: `ec197cef7ccc589fdcae1becc3f4a3de119d0a41e790b898b519b1a048dad8d4`.
- Binario CrispASR: `89cdb449b94e062065b842a2bfad65c3598665f627d99b2feeebee31e0564007`.
- Implementación de generación: `512d950048b1cf59367b583b6de1e45ebdb662047fe0ca6667708a9f16c29424`.
- Implementación de evaluación: `65740c6d09f70ca9554c17b4c7058d0f5d7710fabf4982d9d8dd6793ea4a9669`.
- Manifiesto de identidad de las 40 grabaciones: `fbcbd0d3fa529332fdaa75e3ced1f59f0a7ebb7744a592dbbc8ea6a6a9bd1484`.
- Congelación conjunta `cohort-frozen.json`: `38a5602b9cdf5521bf20beffbecb4992904dcaa5f26331874d7df5b19c2d24de`.

Cada salida fija además el hash del audio completo, mapa base, texto reconocido y JSON crudo. La congelación conjunta se escribió a las **18:18:26 UTC**, antes de abrir las referencias para esta evaluación; las 40 salidas estaban presentes. Las transcripciones de los dos casos piloto se reprodujeron byte por byte. El tiempo de pared medido fue **1.032,95 segundos, unos 17 min 13 s**; la suma de tiempos por canción fue 1.030,65 segundos y su mediana 21,065 segundos. El máximo residente fue 1.941.356.544 bytes, aproximadamente 1,81 GiB, sin intercambios a disco. No se reprodujo audio.

| Corpus completo | WER mediano de la base → Qwen | Mejora / empeora / igual | WER ≤5 %, base → Qwen | WER ≤1 %, base → Qwen |
|---|---:|---:|---:|---:|
| Total, 40 | 6,72 % → 14,49 % | 9 / 30 / 1 | 17 → 7 | 4 → 0 |
| Español, 20 | 7,88 % → 17,48 % | 3 / 17 / 0 | 7 → 2 | 1 → 0 |
| Inglés, 20 | 5,63 % → 10,80 % | 6 / 13 / 1 | 10 → 5 | 3 → 0 |

El CSV público [generacion-qwen-2026-11-21.csv](generacion-qwen-2026-11-21.csv) contiene las 40 métricas, idiomas y hashes, sin letras ni rutas privadas. Su SHA-256 es `eaa862bcb6f6172ec4102855db81fffae98df9351669a24211c9811ae97ae222`. Se conservan localmente `cohort-frozen.json`, `evaluation.json`, `summary-by-language.json` y, por canción, `frozen.json`, `raw.json`, `lyrics.txt` e `inference.log`; el registro de recursos está en `build/generation-next/qwen/mix-full-v1.log`.

La primera ejecución posterior de las pruebas en Windows detectó escritura implícita con CP1252 en los fixtures Unicode. Se corrigieron los fixtures y la lectura/escritura del adaptador para declarar UTF-8. No se regeneraron ni sustituyeron predicciones del ensayo del Mac. Se conserva el adaptador exacto anterior en `build/generation-next/qwen/source-at-generation-v1.py`, SHA-256 `fb48711072f0cdad00eafc56cd0f53b64bf0b381cfbccffda173337138c0ede9`, también recuperable desde el commit `35fa2fc`. Las firmas de futuras ejecuciones cambian con esta corrección y exigirán otro directorio de generación.

**Este ensayo no justifica sustituir la ruta de letras actual por Qwen.** La base comparada incluye letras corroboradas y los dos textos corregidos de la evaluación previa; no es una comparación de Qwen contra Whisper aislado. Tampoco se ha medido aquí un mapa completo: WER evalúa palabras, no alineación, altura, ataques ni duración. La cuantización, el modelo y esta fragmentación podrían influir en el resultado, pero atribuirles la regresión requeriría otros ensayos. Las nueve mejoras individuales no permiten seleccionar un ganador por canción usando la referencia y presentar esa selección como un generador autónomo.

## Disponibilidad no equivale a precisión

La propia validación de Karaoke registró una descarga desde YouTube bloqueada por una petición de autenticación en un runner público de GitHub. Ese resultado impide prometer acceso universal sin intervención a través del flujo ensayado. La app debe explicar el fallo de acceso y distinguirlo de una generación que necesita revisión. Las condiciones de descarga son independientes de mejorar letra, altura y duración. No se conserva la cifra de disponibilidad de DALI anteriormente atribuida a la copia no corroborada. [Prueba de origen documentada en Karaoke](generacion-iteracion.md)
