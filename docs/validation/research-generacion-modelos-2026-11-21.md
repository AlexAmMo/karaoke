# Modelos reutilizables para notas y letra: revisión del 21 de noviembre de 2026

## Resultado

La búsqueda no identifica una implementación pública que demuestre letra, altura, ataques y finales casi perfectos para cualquier grabación de YouTube. Se ejecutaron dos vías nuevas sobre las cuarenta grabaciones: **Phoneme-informed note-level singing transcription**, de Yong, Su y Nam, con F0 de FCPE, y una reconstrucción explícitamente experimental de **SingMelody** con la arquitectura pública GAME. Algunas variantes mejoran finales, pero ninguna supera todos los controles de calidad en una canción completa; no se incorporan a producción. Los resultados completos, la incertidumbre del runner de SingMelody y la limitación de procedencia de las voces inglesas figuran al final.

Se leyeron antes [melodia-alternativas.md](melodia-alternativas.md), [tiempos-alternativas.md](tiempos-alternativas.md) y [generacion-iteracion.md](generacion-iteracion.md). Por ello no se propone repetir SOME, ROSVOT, la votación entre modelos, Sylla o Basic Pitch como descubrimientos nuevos. Basic Pitch ya se ejecutó sobre ocho grabaciones completas y su consenso no bastó para aprobarlas.

## Primera prueba: límites musicales con información fonética

El [modelo oficial de ICASSP 2023](https://github.com/seyong92/phoneme-informed-note-level-singing-transcription) combina espectrograma y probabilidades fonéticas. Sus tres salidas son ataque, final y actividad vocal. Esto aborda específicamente el cambio de sílaba manteniendo el mismo tono, una señal diferente de ajustar ataques a energía o al primer grafema alineado. No transcribe la letra. El [decodificador publicado](https://github.com/seyong92/phoneme-informed-note-level-singing-transcription/blob/b2fcd9ea0f7898a8989c7e65781052d1ffc81094/phn_ast/decoding.py) acepta `f0` externo; pYIN solo se ejecuta cuando falta.

| Aspecto | Evidencia y consecuencia |
| --- | --- |
| Código y licencia | Commit `b2fcd9ea0f7898a8989c7e65781052d1ffc81094`; [MIT](https://github.com/seyong92/phoneme-informed-note-level-singing-transcription/blob/b2fcd9ea0f7898a8989c7e65781052d1ffc81094/LICENSE). |
| Pesos | [Release 0.1.0, model.pt](https://github.com/seyong92/phoneme-informed-note-level-singing-transcription/releases/tag/0.1.0), 106.129.108 bytes. SHA-256 `e56d1c7438f10afb61bbfe54a856a0355d4556fca6038dc67567fe68930ade17`, declarado por el [puntero LFS](https://raw.githubusercontent.com/seyong92/phoneme-informed-note-level-singing-transcription/b2fcd9ea0f7898a8989c7e65781052d1ffc81094/checkpoints/model.pt) y contrastado con la descarga local. |
| Tiempos | El [runner](https://github.com/seyong92/phoneme-informed-note-level-singing-transcription/blob/b2fcd9ea0f7898a8989c7e65781052d1ffc81094/infer.py) convierte los índices a segundos mediante `hop_length / sample_rate`. Son tiempos físicos; el BPM solo sirve para escribir MIDI. |
| CPU y M4 | La interfaz admite `--device cpu`. Después de la inspección se ejecutaron las cuarenta grabaciones en el M4 real, como se detalla al final. Windows no se ha probado para este modelo. MPS no está validado por el proyecto. |
| Memoria | Los LSTM dividen internamente la secuencia en bloques de 512 pasos, pero las convoluciones reciben el audio completo. Conviene comenzar con ventanas cortas. [Implementación](https://github.com/seyong92/phoneme-informed-note-level-singing-transcription/blob/b2fcd9ea0f7898a8989c7e65781052d1ffc81094/phn_ast/subnetworks.py). |

El [artículo](https://arxiv.org/html/2304.05917) comunica F1 de ataque 0,9305 y F1 conjunto de ataque, altura y final 0,7728 en ISMIR2014. El segundo valor es el relevante para un mapa completo. La comparación con Omnizart da 0,7951 y 0,4992, respectivamente; no compara GAME. Los experimentos usan canto aislado y ejercicios, no el conjunto español/inglés de Karaoke. El clasificador fonético utiliza inglés TIMIT o coreano CSD según la variante. No consta validación específica en español. La mejora de ataques de la misma altura justifica un ensayo, pero no demuestra superioridad sobre GAME ni generalización a voces separadas de mezclas comerciales.

### Comandos mínimos y adaptación necesaria

Esta es la ruta del autor, fijando revisión y evitando que Git descargue automáticamente el peso. Son instrucciones de reproducción, **no comandos ejecutados en esta revisión**. Debe reutilizarse un entorno de experimentos compatible; el proyecto original declara PyTorch 1.13.1, torchaudio 0.13.1, nnAudio 0.3.2 y versiones antiguas de NumPy/librosa. No conviene instalar todo de nuevo en este Mac con poco disco.

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/seyong92/phoneme-informed-note-level-singing-transcription /tmp/karaoke-phn-ast
git -C /tmp/karaoke-phn-ast checkout b2fcd9ea0f7898a8989c7e65781052d1ffc81094
curl -fL https://github.com/seyong92/phoneme-informed-note-level-singing-transcription/releases/download/0.1.0/model.pt -o /tmp/karaoke-phn-ast/checkpoints/model.pt
python -c "import hashlib,pathlib; p=pathlib.Path('/tmp/karaoke-phn-ast/checkpoints/model.pt'); assert hashlib.sha256(p.read_bytes()).hexdigest() == 'e56d1c7438f10afb61bbfe54a856a0355d4556fca6038dc67567fe68930ade17'"
cd /tmp/karaoke-phn-ast
python infer.py checkpoints/model.pt /ruta/voz-20s.wav /tmp/phn-ast.mid --device cpu
```

El último comando reproduce el [README del autor](https://github.com/seyong92/phoneme-informed-note-level-singing-transcription/blob/b2fcd9ea0f7898a8989c7e65781052d1ffc81094/README.md), que usa pYIN. Para el ensayo con FCPE hace falta un adaptador de experimentos: cargar el checkpoint en CPU, construir `TranscriptionModel(config)`, llamar al modelo y después a `FramewiseDecoder(config).decode(pred, f0=...)`. La rejilla del F0 debe coincidir exactamente con `config['hop_length'] / config['sample_rate']`; el artículo describe 20 ms a 16 kHz. Interpolar únicamente tramos sonoros y conservar los no sonoros como `NaN`.

Para un PyTorch actual debe hacerse explícita la carga compatible del checkpoint original, `torch.load(path, map_location='cpu', weights_only=False)`, en ese adaptador. El runner antiguo usa `torch.load(path)` y no garantiza cargar en una máquina sin CUDA. Esta adaptación se implementó y verificó después en el Mac, como se detalla al final; sigue sin verificarse en Windows.

### Ensayo propuesto, congelado antes de consultar referencias

1. Probar un fragmento de 20 s con voces y otro de silencio; registrar memoria, tiempo, forma de salida y finitud. Mantener CPU y un único proceso.
2. Generar probabilidades con contexto solapado sobre las 40 voces existentes, conservando la misma separación y SHA del audio. Empezar por núcleos de 20 s con 2 s de contexto; descartar márgenes y sumar el desplazamiento absoluto. Esos tamaños son una elección experimental, no una recomendación del artículo.
3. Comparar dos variantes predefinidas: reconstrucción de límites del modelo con F0 FCPE, y ajuste conservador de límites de GAME a picos compatibles dentro de ±80 ms. Mantener letra y altura de GAME en la segunda variante. No ajustar umbrales por canción a partir del mapa humano.
4. Guardar predicciones y hashes antes de evaluarlas. Informar ataque, final, F1 de nota completa, cobertura, notas espurias y resultados ES/EN por separado. Contar también cuántas canciones completas superan todos los controles actuales. Una mejora de ataques que empeore finales o excluya muchos casos no cumple el objetivo.

## Modelos recientes que no justifican sustituir el sistema

| Candidato | Qué puede reutilizarse | Límite que cambia la decisión |
| --- | --- | --- |
| **VocalParse, mayo 2026** | [Código](https://github.com/pymaster17/VocalParse) y [checkpoint](https://huggingface.co/pymaster/VocalParse), Apache-2.0. Produce letra, MIDI, valores musicales y BPM. | Principalmente mandarín; no predice duraciones físicas y exige cortar segmentos mayores de 30 s. La ficha contiene unos 2.000 millones de parámetros BF16. No aporta por sí solo ataques/finales para puntuar y excede el presupuesto deseable de descarga. |
| **SingMelody** | [Checkpoint GAME multilingüe MIT](https://huggingface.co/pymaster/SingMelody), ES/EN y otros siete idiomas; condicionado a palabras previamente alineadas. | El [repositorio enlazado](https://github.com/pymaster17/SingMelody) devuelve 404 en esta revisión. No puede reproducirse su CLI sin recuperar o reconstruir la inferencia. La propia ficha comunica F1 de melismas ES 0,5813 y EN 0,7353; son métricas condicionadas y no comparables directamente entre idiomas. Sin palabras, la ficha admite errores altos fuera del chino. |
| **SongTrans** | El [artículo](https://arxiv.org/html/2409.14619v1) explica predicción conjunta de letra, duración de palabras, número de notas, alturas y duraciones. | No se localizó una distribución oficial de código y pesos enlazada por el artículo. Licencia de implementación y ejecución no comprobables. WER de letra 10,81 %, WER de alturas 22,45 % y MAE de duración 161,7 ms no equivalen a casi perfección. |
| **T3MS, 2025** | [Método de notas, tiempos y valores musicales](https://arxiv.org/html/2502.12438v1). | No se encontró checkpoint oficial en el artículo. Su F1 combinado con valor musical en HSD es 0,351; no confundir acierto del valor en notas ya correctas con cobertura total. |
| **MusicDETR, ICASSP 2026** | [Repositorio del autor](https://github.com/ChenMengqiao/musicDETR). | Solo README, dependencias y entrenamiento parcial; anuncia completar el código posteriormente. No ofrece inferencia ni pesos reproducibles. |
| **MusicYOLO / Omnizart** | Implementaciones anteriores con extracción de notas. [MusicYOLO](https://github.com/itec-hust/MusicYOLO), [Omnizart](https://github.com/Music-and-Culture-Technology-Lab/omnizart). | MusicYOLO ofrece sus pesos vía Baidu y entorno CUDA antiguo. La comparación del artículo fonético favorece probar primero el modelo pequeño propuesto; no hay evidencia nueva de superioridad sobre GAME en estas cuarenta canciones. |

En VocalParse, la [tabla del artículo](https://arxiv.org/html/2605.04613v1) distingue inferencia solo con audio de inferencia con letra verdadera: en Opencpop el MAE de altura baja de 0,56 a 0,35 semitonos al proporcionar texto, mientras ROSVOT figura con 0,38. No se debe atribuir al caso automático el resultado condicionado. Su [cargador](https://github.com/pymaster17/VocalParse/blob/main/vocalparse/model.py) elige CUDA o CPU, sin ruta MPS; carga base y checkpoint por separado, agravando la memoria máxima. No se ha ejecutado aquí.

El peso de SingMelody anunciado en la [API del repositorio de modelos](https://huggingface.co/api/models/pymaster/SingMelody/tree/main?recursive=true&expand=false) ocupa 588.741.844 bytes, con SHA-256 `8553ef3bdac2ee0b27ab427c1f727fea62dcbb58c528562c6cab8ec4a389ff53`. Contiene estado del optimizador. La compatibilidad exacta de la arquitectura se comprobó después, pero sigue faltando el runner original: la ficha describe inferencia condicional de un paso y vocabulario por idioma, sin especificar todo el decodificador.

## Interpretación de resultados recientes y límites de la revisión

La [página original de resultados de letras MIREX 2026](https://www.music-ir.org/mirex/wiki/2026:Lyrics_Transcription_Results) devolvió un error al consultarla. Se localizó una copia de lectura en otro dominio, pero no se ha confirmado que pertenezca a los organizadores; no se usa para establecer cifras oficiales. No se identificó una tabla oficial reciente de notas cantadas que permita afirmar que existe un sustituto superior a GAME en ES/EN. En cualquier caso, una competición de texto por sí sola no evalúa mapas de notas ni tiempos de puntuación.

La inspección de fuentes y código está terminada. El resultado útil para desarrollar ahora es una hipótesis concreta y barata sobre límites musicales, con pesos y código públicos, separada de las afirmaciones comerciales o de laboratorio sobre transcripción universal.

## Adaptador preparado y validación inicial

[phoneme_notes.py](../../scripts/experiments/phoneme_notes.py) ejecuta ventanas de 18 s con 2 s de contexto, reúne los logits en la rejilla absoluta de 20 ms y decodifica una vez usando los fotogramas pares del FCPE de 10 ms. Conserva como no sonoros los ceros de FCPE. Emite los formatos `pitch` y `events` de `melody_compare.transform`, hashes de WAV/predicción/pesos/código y probabilidades guardadas. No tiene argumento de referencia humana. Rechaza contornos cuya huella del WAV difiera; puede regenerar FCPE sobre esa misma voz local con el modelo distribuido.

La descarga de 106 MB y la carga completa se verificaron en el Mac M4: 24.336.970 parámetros, todas las claves compatibles, 39 etiquetas fonéticas y rejilla de 16 kHz/320 muestras. Se reutilizó el entorno existente con PyTorch/torchaudio 2.8.0, librosa 0.11.0, NumPy 2.5.5 y soxr 1.1.0; solo se añadieron nnAudio 0.3.2 y wquantiles 0.6 sin dependencias adicionales. Compilación Python y pruebas sintéticas del decodificador, silencio, unión de ventanas y rechazo de contornos incompletos pasaron.

Se comprobó que los veinte contornos españoles cacheados pertenecen a las mismas voces guardadas. Los ingleses proceden de otra separación remota y no pasan la comparación SHA; se regeneraron con FCPE para el WAV exacto del ensayo. Las voces inglesas actuales proceden de siete separaciones del Mac y trece de un runner, aunque la inferencia PPG/FCPE de esta sesión se ejecutó en el Mac. El piloto de Amorfoda y Mr. Fancy Pants tardó 9,49 s en total, incluidos arranque y carga, con pico RSS de 1.249.689.600 bytes. La extensión a los otros treinta y ocho temas tardó 234,83 s, con pico RSS de 1.412.136.960 bytes y cero intercambios a disco comunicados por `/usr/bin/time -l`. Se mantuvieron CPU con dos hilos y los mismos parámetros. La inferencia nueva se comprobó en hardware M4 real; no se ejecutó en Windows virtual ni real.

Antes de abrir las referencias se fijó una tercera variante, `boundaries`: conservar todas las notas, letras y alturas del mapa base y mover límites a candidatos PPG a un máximo de ±80 ms. Exige coincidencia individual, al menos 35 ms de solape y soporte de voz FCPE más actividad PPG junto al límite. Rechaza movimientos que introduzcan solapes o duraciones inferiores a 35 ms, que en la rejilla de 1/60 s significa 50 ms para notas modificadas. Las pruebas sintéticas verificaron dos notas sucesivas del mismo tono, un límite compartido, silencio acústico y ausencia de F0; los silencios no arrastraron límites.

## Comparación completa, sin ajustar parámetros a las referencias

Se congelaron 120 mapas, sus cuarenta eventos y logits. Después se ejecutó [evaluate_generation_candidate.py](../../scripts/experiments/evaluate_generation_candidate.py) con `--near-perfect` para las tres variantes y la misma base de `build/generation-v3/lyrics/final/charts.json`. Cada variante tiene cuarenta resultados válidos y ninguno ausente. Esta base es una predicción experimental; no sustituye el turno verificado de Amorfoda conservado para la entrega.

**Limitación de la comparación con la base:** se verifican los mismos cuarenta másteres, pero las veinte predicciones inglesas históricas no registraron SHA-256 de la voz separada que recibieron. No se puede atribuir toda diferencia frente a esa base únicamente a PPG. Los resultados comparan la cadena ensayada con la histórica; los tres brazos nuevos sí comparten exactamente el mismo WAV y F0. Regenerar el FCPE inglés corrige la procedencia dentro del ensayo nuevo, pero no reconstruye la huella ausente de las entradas históricas. Véase también [generacion-fiabilidad-2026-11-21.md](generacion-fiabilidad-2026-11-21.md).

Las cifras son medianas por canción, con veinte grabaciones por idioma. `Clase` mide clase de altura correcta sobre todos los fotogramas de referencia; `Ataque` exige altura y ataque; `Nota completa` añade el final; `Precisión temporal` es `scored_frame_precision` del evaluador común.

| Muestra | Variante | Clase | Ataque F1 | Nota completa F1 | Precisión temporal | Cobertura |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 40 | Base | 76,48 % | 0,6677 | 0,0854 | 50,26 % | 96,05 % |
| 40 | pitch | 72,29 % | 0,5876 | 0,0754 | 46,66 % | 96,05 % |
| 40 | events | 64,65 % | 0,5972 | 0,1419 | 49,02 % | 81,80 % |
| 40 | boundaries | 70,77 % | 0,6565 | 0,1125 | 51,16 % | 87,84 % |
| ES | Base | 71,53 % | 0,6096 | 0,1157 | 49,93 % | 94,72 % |
| ES | pitch | 66,91 % | 0,5573 | 0,1108 | 46,59 % | 94,72 % |
| ES | events | 61,24 % | 0,5444 | 0,1864 | 47,68 % | 78,11 % |
| ES | boundaries | 67,59 % | 0,6072 | 0,1640 | 51,76 % | 85,83 % |
| EN | Base | 78,79 % | 0,7250 | 0,0676 | 50,77 % | 96,97 % |
| EN | pitch | 73,46 % | 0,6295 | 0,0576 | 46,93 % | 96,97 % |
| EN | events | 66,01 % | 0,6050 | 0,1261 | 50,17 % | 83,98 % |
| EN | boundaries | 73,24 % | 0,7153 | 0,0897 | 50,76 % | 89,34 % |

`boundaries` mejora el F1 con finales en 32 temas, conserva dos y empeora seis; la precisión temporal mejora en 26. Sin embargo, empeora la clase correcta sobre el total en los cuarenta temas y el ataque F1 en veintinueve. La reconstrucción completa mejora los finales en 32, pero reduce todavía más cobertura y altura. Las letras se conservan, por lo que la mediana WER permanece en 6,72 % global, 7,88 % ES y 5,63 % EN. La mediana del p90 de palabra pasa de 107 ms en la base a 109 ms en `boundaries`.

Ninguna de las tres variantes supera los cinco controles conjuntos en ninguna de las cuarenta canciones; ninguna cumple el objetivo casi perfecto. La base tampoco supera los cinco; sí conserva una aprobación con los cuatro controles iniciales, que las variantes pierden. No se cambiaron parámetros después de ver estas mediciones. La mejora parcial de finales no compensa la pérdida de voz cubierta y no justifica sustituir GAME.

El [CSV de 160 filas](generacion-ppg-2026-11-21.csv) conserva cada resultado, idioma y huella de la evaluación. Los manifiestos, logits y evaluaciones detalladas permanecen en `build/generation-next/phoneme/results/`. Esta muestra ya había informado el desarrollo: sirve para regresión y comparación controlada, no para certificar fiabilidad en canciones desconocidas.

## Seguimiento de SingMelody: arquitectura comprobada, runner reconstruido

Se descargó el checkpoint de [SingMelody fijado a la revisión `c0ba47c`](https://huggingface.co/pymaster/SingMelody/tree/c0ba47cf22a1fe4de9b3d8e480415a9e53c67869) y se contrastó su SHA-256. Tras la descarga quedaban 6,88 GiB disponibles. `torch.load(weights_only=True, mmap=True)` permite inspeccionarlo sin cargar el optimizador en memoria física. Contiene 671 tensores y 49.887.251 parámetros, sin EMA ni configuración adicional que revele el valor constante de `t`.

La arquitectura pública [GAME `69ba01d`](https://github.com/openvpi/GAME/tree/69ba01ded0ddda5495e51ba373685f1be1a67ea2) acepta exactamente las 671 claves y formas con `strict=True`: cero ausentes, cero sobrantes, cero discrepancias. Solo se remapeó el prefijo de importación `singmelody.game.upstream._modules` a `modules`; no se modificaron capas. La comprobación está guardada en `build/generation-next/singmelody/architecture-check.json`.

| Componente publicado | Configuración confirmada en las claves |
| --- | --- |
| Entrada y encoder | 80 bandas → 256 canales; EBF de cuatro capas; salida de 512 canales dividida en segmentación/altura. |
| Segmentador | EBF de ocho capas; salida de un logit por fotograma; proyección latente de 16 canales. |
| Idioma | Matriz de 128×256; mapa español=8, inglés=5 y otros siete idiomas. |
| Alturas | JEBF de cuatro capas; 257 bins entre MIDI 0 y 128. |
| Reloj | 44.100 Hz, salto 441 muestras: 10 ms. |

La compatibilidad estructural no recupera las decisiones ausentes del runner original. La ficha solo indica una pasada a `t` constante; no especifica su valor ni los umbrales. [El código público GAME](https://github.com/openvpi/GAME/blob/69ba01ded0ddda5495e51ba373685f1be1a67ea2/modules/midi_extraction.py) sí expone encoder, segmentación y estimación por separado. Se preparó [singmelody_notes.py](../../scripts/experiments/singmelody_notes.py) como reconstrucción experimental identificada explícitamente, sin afirmar que reproduzca los resultados publicados por SingMelody.

Antes de consultar referencias se fijaron cuatro brazos: `free-t0`, `words-t0`, `free-t1`, `words-t1`. En `words` se incluyen inicios y finales de las palabras del mapa predicho, respetando también sus huecos; no se usan palabras ni tiempos de la referencia humana. El encoder se comparte entre los cuatro brazos. La segmentación recibe una vez la máscara de regiones, sin muestreo D3PM. Se aplican los [valores CLI de GAME](https://github.com/openvpi/GAME/blob/69ba01ded0ddda5495e51ba373685f1be1a67ea2/infer.py): umbral de límite 0,2, radio 20 ms y umbral de presencia 0,2. `t=1` es una hipótesis para la llamada directa de la red: el CLI D3PM original no acepta ese extremo.

El adaptador pasó compilación, carga estricta en CPU y comprobaciones sintéticas de intervalos de palabras/silencio, repetición del mismo tono y unión de ventanas. Una revisión independiente detectó que errores submicrosegundo al acumular duraciones podían fusionar notas repetidas en una frontera. Antes de inferir se corrigió el reloj para acumular fotogramas enteros y normalizar las coordenadas a seis decimales; el caso de dos ataques del mismo tono a ambos lados de 12 s conserva ahora ambos ataques. Se fijaron ventanas de 12 s con 1,5 s de contexto y dos hilos CPU. No se modificó producción.

### Ejecución completa y reproducción

El piloto predeterminado de Amorfoda, 11 y 6, Mr. Fancy Pants y Northern Star produjo 32 mapas válidos, con eventos finitos y sin solapes. Se comprobó únicamente su estructura antes de extender a las cuarenta canciones; no se consultó el mapa humano para decidir la extensión. Los cuatro brazos mantuvieron exactamente código, parámetros y entradas. Cada brazo genera `pitch`, que cambia alturas sobre los tiempos base cuando existe suficiente solape, y `events`, que reconstruye notas usando los eventos nuevos y las sílabas predichas existentes.

La ejecución se hizo en el **MacBook Pro M4 real**, con CPU y dos hilos, sin otras redes concurrentes. El piloto tardó 127,11 s y alcanzó 736.559.104 bytes de RSS; las otras 36 canciones tardaron 1.301,15 s y alcanzaron 723.632.128 bytes. En ambas ejecuciones `/usr/bin/time -l` comunicó cero swaps. En total, las cuarenta canciones y los cuatro brazos necesitaron 23 min 48 s, incluidos dos arranques y cargas. No se reprodujo audio y el Mac permaneció silenciado. No se probó este adaptador en Windows, ni en máquina virtual ni en hardware real; no forma parte de los instaladores.

Comando ejecutado para la extensión completa, reutilizando el piloto congelado:

```bash
build/generation-bench/env/bin/python scripts/experiments/singmelody_notes.py \
  --model-dir build/generation-next/singmelody \
  --source build/generation-next/singmelody/game \
  --stems build/generation-v3/shared/stems.json \
  --charts build/generation-v3/lyrics/final/charts.json \
  --output build/generation-next/singmelody/results \
  --threads 2 --core 12 --pad 1.5
```

El plan anterior al audio está en `build/generation-next/singmelody/predeclared-plan.json`; el SHA-256 del adaptador es `40f0ef07a6bc0a5ec7e9eddbf2f8909ca6caeed7f12873c9ca58fcf3d91d1a77`. Se conservó una copia de los siete archivos de implementación y sus hashes, los dos manifiestos de entrada, la configuración/ficha/mapa de idiomas y un archivo Git de GAME en `results/source-snapshot/`. Las 160 predicciones de eventos registran el SHA de la voz y del mapa base; los 320 mapas conservan sus hashes. Todos los manifiestos comunes se congelaron antes de abrir las referencias. La evaluación usa el mismo `evaluate_generation_candidate.py --near-perfect`, sin ajuste de desplazamiento, altura o parámetros por referencia.

### Resultados de los ocho conjuntos fijados

Cada conjunto tiene **40 resultados válidos, cero ausentes y cero inválidos**. Los ocho obtienen **0/40 con los cinco controles** y **0/40 con el objetivo casi perfecto**. También pierden la única aprobación de la base con los cuatro controles antiguos. Esta base experimental no reemplaza el turno verificado de Amorfoda de la entrega.

Las cifras siguientes son medianas por canción, con las mismas definiciones de la comparación PPG. Se muestran todos los brazos; no se escoge un ganador a partir de las referencias.

| Variante | Clase | Ataque F1 | Nota completa F1 | Precisión temporal | Cobertura |
| --- | ---: | ---: | ---: | ---: | ---: |
| Base | 76,48 % | 0,6677 | 0,0854 | 50,26 % | 96,05 % |
| free-t0-pitch | 66,03 % | 0,5203 | 0,0733 | 43,38 % | 96,05 % |
| free-t0-events | 63,74 % | 0,4793 | 0,0963 | 39,47 % | 95,24 % |
| words-t0-pitch | 66,86 % | 0,5281 | 0,0692 | 43,37 % | 96,05 % |
| words-t0-events | 65,27 % | 0,5363 | 0,0600 | 41,25 % | 96,92 % |
| free-t1-pitch | 63,98 % | 0,5240 | 0,0696 | 42,79 % | 96,05 % |
| free-t1-events | 62,16 % | 0,4777 | 0,0915 | 38,78 % | 95,22 % |
| words-t1-pitch | 66,86 % | 0,5282 | 0,0692 | 43,38 % | 96,05 % |
| words-t1-events | 65,23 % | 0,5320 | 0,0591 | 41,44 % | 96,72 % |

| Idioma | Variante | Clase | Ataque F1 | Nota completa F1 | Precisión temporal |
| --- | --- | ---: | ---: | ---: | ---: |
| ES | Base | 71,53 % | 0,6096 | 0,1157 | 49,93 % |
| ES | free-t0-pitch | 60,34 % | 0,4605 | 0,1058 | 42,85 % |
| ES | free-t0-events | 61,73 % | 0,4724 | 0,1203 | 38,28 % |
| ES | words-t0-pitch | 61,02 % | 0,4877 | 0,0980 | 42,08 % |
| ES | words-t0-events | 62,14 % | 0,4779 | 0,0992 | 40,61 % |
| ES | free-t1-pitch | 59,63 % | 0,4599 | 0,1039 | 42,80 % |
| ES | free-t1-events | 59,27 % | 0,4534 | 0,1097 | 38,24 % |
| ES | words-t1-pitch | 60,13 % | 0,4854 | 0,0970 | 41,92 % |
| ES | words-t1-events | 60,96 % | 0,4771 | 0,0964 | 40,32 % |
| EN | Base | 78,79 % | 0,7250 | 0,0676 | 50,77 % |
| EN | free-t0-pitch | 67,56 % | 0,5654 | 0,0585 | 43,40 % |
| EN | free-t0-events | 65,93 % | 0,4912 | 0,0825 | 39,77 % |
| EN | words-t0-pitch | 71,28 % | 0,6013 | 0,0572 | 44,47 % |
| EN | words-t0-events | 70,01 % | 0,6014 | 0,0494 | 42,16 % |
| EN | free-t1-pitch | 66,78 % | 0,5565 | 0,0606 | 42,79 % |
| EN | free-t1-events | 63,84 % | 0,4978 | 0,0832 | 39,40 % |
| EN | words-t1-pitch | 71,40 % | 0,5976 | 0,0572 | 44,29 % |
| EN | words-t1-events | 69,79 % | 0,6001 | 0,0482 | 42,38 % |

Las letras se reutilizan: la mediana WER sigue en 6,72 % global, 7,88 % ES y 5,63 % EN en los ocho conjuntos. `pitch` conserva también el p90 de palabra de la base, 107 ms global. Con `events` libre aumenta a 128,5 ms para t0 y 127 ms para t1; condicionado a palabras queda en 109,5 ms en ambos casos. Por tanto, este experimento tampoco resuelve la transcripción de texto.

La reconstrucción ensayada reduce las medianas de altura, ataque y precisión temporal frente a la cadena base en ambos idiomas. La pequeña mejora de F1 con finales de algunos brazos libres no produce canciones listas para jugar. **Esto descarta promover esta reconstrucción concreta; no demuestra que SingMelody sea incapaz con su runner original.** La carga estricta de 671 claves prueba arquitectura, no equivalencia de inferencia. El valor real de `t`, otras decisiones del decodificador y el comportamiento del repositorio que devuelve 404 siguen sin verificarse.

La comparación con la base mantiene la limitación de procedencia ya descrita: los veinte mapas ingleses históricos no registraron SHA de su voz separada; las voces actuales proceden de siete separaciones del Mac y trece del runner. Todos los brazos nuevos comparten las mismas voces y mapas base, pero no puede atribuirse toda diferencia histórica exclusivamente al modelo. Las cuarenta grabaciones son una muestra de desarrollo, no una prueba independiente de generalización a cualquier vídeo.

El [CSV completo de 360 filas](generacion-singmelody-2026-11-21.csv) contiene los cuarenta casos de cada conjunto y de la base, con hashes y métricas. Los nueve manifiestos/evaluaciones, las medianas globales y por idioma y los conteos de comparación por canción están en `build/generation-next/singmelody/results/evaluation/`, con resumen `summary.json`. No se cambiaron parámetros ni se promovió un brazo después de leer los resultados.
