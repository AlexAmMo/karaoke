# ¿Puede este Mac convertir una canción de YouTube en un karaoke puntuable?

**Sí puede producir un borrador en algo más de un minuto. La precisión observada permitiría ahorrar parte de la edición, pero todavía penalizaría a personas que cantan bien.** El 21 de noviembre de 2026 generamos dos mapas completos, sin suministrar letras, tonos, tiempos, títulos ni mapas al generador. Después los comparamos con las ediciones que ya se usan para cantar en Karaoke. Ambos borradores pasaron el mismo validador de archivos que usa la aplicación.

## Tiempo medido en el equipo

Apple M4 de 10 núcleos, 16 GiB de memoria, macOS 26.6.2 arm64 y Python 3.12.12. Usamos CPU con cuatro hilos para el separador y cuatro para el reconocedor, en etapas consecutivas. La reproducción de la sesión y el micrófono de los jugadores estuvieron fuera del ensayo.

| Tiempo en segundos | Sigo Aquí · Álex Ubago | Go The Distance · Michael Bolton |
|---|---:|---:|
| Duración de la grabación | 224,68 | 277,15 |
| Decodificar la mezcla a estéreo 44,1 kHz | 0,20 | 0,16 |
| Cargar Demucs desde caché | 0,34 | 0,27 |
| Separar la voz | 52,55 | 71,53 |
| Cargar Whisper desde caché | 0,60 | 0,63 |
| Transcribir la voz y fechar palabras | 15,95 | 16,71 |
| Estimar tono, construir TXT y validar con Karaoke | 0,39 | 0,50 |
| **Proceso completo, reloj de pared** | **71,59** | **91,58** |

El reloj de pared incluye el inicio y salida del proceso, las importaciones y la evaluación frente a la referencia. Hicimos una primera pasada de preparación y otra completa por canción con el mismo script y modelos locales. Los números de la tabla son de la segunda pasada. En cada canción el TXT producido fue idéntico byte a byte en ambas ejecuciones. Pueden cambiar con la carga del equipo, el modelo, el idioma y la duración.

Para *Sigo Aquí* repetimos también el paso de red con la función de descarga de Karaoke y el identificador exacto de YouTube `IA0uSub1xy4`. Tardó **8,95 s** en extraer y convertir el audio a MP3. El SHA-256 y los 5.393.708 bytes coinciden con la grabación usada en el ensayo. La suma de las dos mediciones da **80,54 s desde el enlace hasta el borrador** en esta conexión y con los modelos ya instalados. *Go The Distance* partió de una edición preparada en disco, de modo que su tiempo empieza al abrir el audio. [Grabación de Sigo Aquí](https://www.youtube.com/watch?v=IA0uSub1xy4) · [Validación anterior de la misma edición](catalog-acoustic-check.json)

La primera descarga de Whisper tardó 9,73 s. La primera obtención y carga de Demucs tardó 3,30 s. En este Mac el entorno de investigación ocupó aproximadamente 723 MiB, los pesos de Whisper 464 MiB y la caché de Demucs 85 MiB. Dos WAV temporales por canción ocuparon 151 y 187 MiB respectivamente. Estos modelos y dependencias pertenecen al ensayo y quedan fuera del instalador.

## Qué tan bien se puede cantar el resultado

| Comparación con la edición comunitaria | Sigo Aquí (español) | Go The Distance (inglés) |
|---|---:|---:|
| Palabras en referencia / borrador | 219 / 215 | 252 / 259 |
| Ediciones de palabras / WER | 27 / **12,3 %** | 65 / **25,8 %** |
| Palabras idénticas alineadas | 194 | 201 |
| Error absoluto de inicio de esas palabras, mediana | **210 ms** | **125 ms** |
| Error absoluto de inicio de esas palabras, percentil 90 | **772 ms** | **912 ms** |
| Desfase mediano por tercio, en ms | −141 / −215 / −277 | −131 / −87 / −137 |
| Barras puntuables en referencia / borrador | **414 / 782** | **301 / 1.086** |
| Barras generadas sin tono fiable, marcadas libres | 1 | 1 |
| Tiempo puntuable de la referencia que cubre el borrador | 70,1 % | 81,5 % |
| Tiempo puntuable con la clase de tono exacta | **56,2 %** | **56,5 %** |
| Tiempo puntuable con desviación máxima de un semitono | 63,2 % | 69,3 % |
| F1 de inicios con tono correcto, tolerancia 100 ms | **0,463** | **0,252** |

En *Sigo Aquí*, el borrador recuperó bastante texto y adelantó de forma creciente la entrada típica de las palabras. En *Go The Distance*, produjo más de tres barras por cada barra dibujada por el editor. La separación vocal y la transcripción tardan poco, pero la medición de frecuencia sigue los cambios breves de la voz e introduce demasiadas notas. Un ajuste global de sincronización tampoco recuperaría palabras ausentes, separaría sílabas o corregiría la duración de los melismas. Los borradores escriben la palabra entera en la primera barra y una prolongación en las siguientes. Una letra silabeada como la que se espera en pantalla exige otra etapa.

## Cómo se hizo la comparación

1. FFmpeg decodificó la grabación completa, conservando el origen temporal. HTDemucs aisló la voz con solapamiento 25 % y sin desplazamientos aleatorios. La canción original con la voz del artista sigue siendo la mezcla de reproducción. [Demucs](https://github.com/adefossez/demucs)
2. Faster Whisper Small multilingüe en int8 transcribió la voz a 16 kHz, con idioma conocido, cinco candidatos por paso, tiempos de palabra, sin VAD y sin arrastrar texto del segmento anterior. [Faster Whisper](https://github.com/SYSTRAN/faster-whisper) · [Modelo Small](https://huggingface.co/Systran/faster-whisper-small)
3. Praat por autocorrelación extrajo la frecuencia fundamental entre 70 y 880 Hz cada 10 ms. Redondeamos a semitonos, aplicamos mediana de siete muestras y conservamos cambios sostenidos durante cuatro muestras dentro de cada palabra. Escribimos un TXT UltraStar de tempo fijo con rejilla de 25 ms. Si faltaba tono en toda la palabra se convirtió en una barra libre. Finalmente abrimos el paquete con `karaoke.songs.validate`. [Praat-Parselmouth](https://parselmouth.readthedocs.io/en/stable/)
4. **La referencia se utilizó exclusivamente después de escribir el archivo.** Para evaluar el borrador reconstruimos sus palabras y las de la referencia a partir de los TXT. Normalizamos mayúsculas y puntuación preservando acentos y unimos sílabas y prolongaciones. La WER es la distancia mínima de edición dividida por las palabras de referencia. Calculamos el error de inicio únicamente en las palabras iguales del alineamiento, incluyendo repeticiones. Los desfases negativos indican entradas anticipadas.
5. Para cada instante de nota puntuable en el mapa humano, a intervalos de 10 ms, comprobamos si el borrador tenía la misma clase de tono en ese instante. El denominador incluye toda nota humana perdida. La comparación admite el cambio de octava y resulta más permisiva que exigir altura absoluta. El F1 empareja una sola vez cada inicio con misma clase tonal y diferencia ≤100 ms, penalizando barras que sobran y que faltan. Conservamos los tiempos originales de ambas ediciones durante la evaluación.

Las dos canciones son solos masculinos de pop con edición comunitaria. La referencia representa la melodía seleccionada por cada editor. La puntuación compara ese criterio de juego con el borrador y no sustituye una transcripción de estudio ni una prueba cantada a ciegas. Faltan duetos, contraltos y sopranos, rap, coros superpuestos, directos, mezclas difíciles, una muestra más amplia de ambos idiomas y mediciones de Windows y de carga durante una sesión. En una canción completamente nueva no habrá mapa humano para calcular estas métricas. Una puntuación interna de confianza necesitará calibrarse antes de tomar decisiones automáticas.

## Consecuencia para el catálogo

Preservar las acciones de un clic para las ediciones existentes verificadas. Si falta una edición, ofrecer generación como trabajo opcional en segundo plano, conservar el audio original y vincular cada borrador al identificador de grabación, huella del audio y versiones de los modelos. Las personas de la sala continúan con otras canciones. El prototipo aquí medido da para ensayar o editar en privado. Publicarlo directamente como opción puntuable introduciría errores visibles.

Para avanzar, comparar sobre las mismas grabaciones palabras alineadas fonéticamente con letra fiable, separación silábica en español e inglés y un extractor de melodía con segmentación musical que suprima vibrato y preserve las notas intencionadas. Usar muestras ajenas al ajuste y comparar con dos editores cuando sus mapas discrepen. Como primera puerta propuesta para un piloto puntuable, en cada idioma y estilo evaluar WER ≤5 %, error p90 del inicio ≤120 ms, clase tonal exacta ≥90 % del tiempo puntuable y F1 de notas ≥0,85, seguidos de sesiones cantadas a ciegas. Estos son objetivos a calibrar con la variación entre editores y con usuarios. [Alineamiento fonético de WhisperX](https://github.com/m-bain/whisperX)

## Reproducción

Desde la raíz del repositorio, con FFmpeg y ffprobe en el PATH, crear un entorno aislado. Los valores usados fueron Demucs 4.1.0, PyTorch y TorchAudio 2.8.0, Faster Whisper 1.2.1, CTranslate2 4.9.0, Praat-Parselmouth 0.4.7, SoundFile 0.14.0, SciPy 1.18.1, NumPy 2.5.5 y FFmpeg 9.0.1. Para la comprobación de red se usó yt-dlp 2026.10.26. [Script de generación y evaluación independiente](../../scripts/benchmark_chart_generation.py)

```bash
bench=build/generation-bench
uv venv --python 3.12 "$bench/env"
uv pip install --python "$bench/env/bin/python" demucs==4.1.0 torch==2.8.0 torchaudio==2.8.0 faster-whisper==1.2.1 ctranslate2==4.9.0 praat-parselmouth==0.4.7 soundfile==0.14.0 scipy==1.18.1 numpy==2.5.5
"$bench/env/bin/python" -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-small', revision='536b0662742c02347bc0e980a01041f333bce120', local_dir='$bench/model', allow_patterns=['*.json','*.txt','model.bin'])"
"$bench/env/bin/python" -c "from demucs.pretrained import get_model; get_model('htdemucs')"
```

Ejecutar una vez por canción con el audio original y un directorio de salida nuevo. La referencia es opcional y sólo participa en la evaluación. El comando conserva materiales intermedios en el directorio privado para inspección. Si se omite `--reference`, escribe el mismo borrador y comunica los tiempos.

```bash
HF_HUB_OFFLINE=1 OMP_NUM_THREADS=4 VECLIB_MAXIMUM_THREADS=4 \
  "$bench/env/bin/python" scripts/benchmark_chart_generation.py \
  "/ruta/audio-original.mp3" es "$bench/model" "$bench/ensayo-es" \
  --reference "/ruta/mapa-comunitario.txt"
```

| Identidad de los materiales medidos | SHA-256 |
|---|---|
| Sigo Aquí, audio | `043e2cecc28b1dbb1ed9521a32567d8c876b425160c9111f5bd1d99c149be393` |
| Sigo Aquí, TXT preparado de Cualquiera98 | `b2f9a73fc0fd2a75446bd20c3c267b231c5ac3a6310c0c1c4b0111f77d72e8cc` |
| Go The Distance, audio | `3df53b7323c0f4168f296bc8ee4080a2f77d89f297455da4e27b4373e88c3f68` |
| Go The Distance, TXT preparado de askusbloodfist, USDB 16859 | `ea55689b51c1479940c1e146c8c9ff5c748f1d373decc62367780526489df9db` |
| Whisper Small, model.bin | `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671` |
| Demucs, 955717e8.safetensors, revisión `cbc8a9b1a87023b7fd74e7b3412e6321c0eab003` | `d9fa14133cfcc034a6758923bb3a8ca9f8dfd0b582134643bbf83f72c17576dd` |

El hash del TXT preparado puede diferir del original público por cabeceras de codificación y por el nombre local del medio. Las mediciones y el script son compartibles sin redistribuir audio ni letras.
