# Generar una canción puntuable a partir de su grabación

Karaoke ya puede analizar la mezcla original y producir un paquete UltraStar auditable. La voz del artista permanece en la reproducción. El separador, la transcripción y la estimación musical trabajan sobre una copia temporal. Un mapa generado empieza como borrador y requiere revisión para entrar en la biblioteca. La selección de canciones con un mapa comunitario verificado mantiene su flujo habitual.

## Cómo se obtiene cada componente

1. **Grabación.** El trabajo de la aplicación conserva el identificador del vídeo elegido, limita la descarga a ese vídeo y vincula el paquete a la huella SHA-256 del audio. El generador decodifica la pista, separa la voz con HTDemucs y vuelve a usar la mezcla para el MP3 reproducible. [Demucs](https://github.com/facebookresearch/demucs)
2. **Letra.** Whisper large-v3-turbo reconoce las palabras cantadas. Se puede aportar la letra, aprovechar subtítulos manuales del mismo vídeo o consultar LRCLIB. Para estos últimos se exige título, intérprete, duración compatible y coincidencia ordenada con las palabras reconocidas. Los tiempos del fichero de letras se descartan. Una letra aportada que diverge claramente de una transcripción suficientemente larga da un error. [Modelo Whisper](https://huggingface.co/openai/whisper-large-v3-turbo) · [API de LRCLIB](https://lrclib.net/docs)
3. **Sílabas.** Un alineador CTC entrenado con voz cantada asigna las sílabas a la interpretación concreta. Una puerta de energía ayuda a evitar los silencios. Un estimador de frecuencia fundamental sitúa el comienzo de la voz. El adaptador de UltrastarCreatorTool procede de una revisión concreta de código GPL y se comprueba al instalar. [Alineador de Tune Studio](https://huggingface.co/tuneperfect/tunestudio-aligner) · [Adaptador y evaluación de seis canciones](https://github.com/retotito/UltrastarCreatorTool/blob/39d3eb5f9fb1e24220c4ca58888af8a88e11a38a/docs/decisions/0002-forced-alignment-of-user-lyrics.md)
4. **Notas.** GAME extrae ataques, finales y alturas en ventanas de 12 s con contexto solapado. La app asocia esos eventos con las sílabas. Un cambio de nota dentro de una misma vocal conserva la prolongación del texto. El final puede extenderse mientras hay eventos vocales continuos. Las palabras sin tono identificable quedan sin puntuación. Una segunda medición con FCPE señala fragmentos en los que conviene escuchar el original. [GAME](https://github.com/openvpi/GAME) · [FCPE](https://github.com/CNChTu/FCPE)
5. **Resultado.** La publicación local del borrador es atómica. El manifiesto contiene las huellas del audio y del TXT, la fuente de letra, las revisiones de modelos y los instantes de baja confianza. El editor permite oír y corregirlos antes de aprobar el paquete. El perfil estándar usa Whisper y pYIN, con menor resolución musical. [Generador](../../src/karaoke/generation_worker.py) · [Dependencias del entorno aislado](../../src/karaoke/generation_assets/requirements.in)

El perfil musical usa pesos no comerciales del alineador (CC BY-NC 4.0) y de GAME (CC BY-NC-SA 4.0). Se obtienen tras elegir ese perfil. El código del proyecto, el código de los motores y los pesos tienen condiciones diferentes. [Pesos de GAME](https://github.com/openvpi/GAME#license) · [Condiciones del alineador](https://huggingface.co/tuneperfect/tunestudio-aligner)

## Qué aportaron las alternativas examinadas

UltraSinger reúne transcripción y estimación de tono en un conversor UltraStar. UltraStarKaraokeMaker parte de una letra que ya se conoce y la alinea con la voz. La distinción importa cuando el reconocedor se salta una palabra o confunde un estribillo. Hemos hecho opcional la letra corroborada para que la vía de solo audio siga funcionando sin cuentas adicionales. [UltraSinger](https://github.com/rakuri255/UltraSinger) · [UltraStarKaraokeMaker](https://github.com/walterfr/UltraStarKaraokeMaker)

SOFA aborda la alineación de voz cantada. ROSVOT y SOME abordan la transcripción melódica. Basic Pitch obtiene MIDI de audio y admite polifonía. GAME publica pesos ejecutables con ONNX y separa la estimación de límites de la estimación de altura. Elegimos esa ruta porque permite probar el resultado contra un mapa humano en los dos sistemas de escritorio que usa Karaoke. [SOFA](https://github.com/qiuqiao/SOFA) · [ROSVOT](https://github.com/RickyL-2000/ROSVOT) · [SOME](https://github.com/openvpi/SOME) · [Basic Pitch](https://github.com/spotify/basic-pitch) · [GAME](https://github.com/openvpi/GAME)

Wav2Karaoke probó una cadena completa en inglés y documentó la pérdida de precisión al combinar reconocimiento, segmentación y notas. Tune Studio publicó una evaluación en 74 canciones inglesas y alemanas con F1 de nota de 0,698 y exactitud de altura de 0,851 con su cadena completa. Sus métricas, idiomas y selección de canciones difieren de los de Karaoke. Sus refinadores de nota usan vectores de características cuya construcción exacta también es parte del sistema. [Wav2Karaoke, Universidad de Tohoku](https://keisuke-sakaguchi.github.io/assets/pdf/2026_nlp_wav2karaoke.pdf) · [Tune Studio](https://huggingface.co/tuneperfect/tunestudio-aligner) · [Refinadores](https://huggingface.co/tuneperfect/tunestudio-note-refiners)

## Iteraciones y controles

Se usaron *Sigo aquí* y *Go the Distance* para elegir el método de segmentación. El resto de mapas humanos se reservaron para medir resultados. Cada generador recibió audio y metadatos o una letra procedente de una fuente independiente. El comprobador abrió el mapa de referencia al calcular errores. No se corrigió el desfase de cada mapa para favorecer las métricas. Los borradores y las grabaciones permanecieron en directorios de trabajo privados.

| Variante sobre «Sigo aquí» | Error de palabras | Inicio de palabra p90 | Clase de nota correcta | F1 de ataques |
|---|---:|---:|---:|---:|
| Whisper small y Praat | 12,3 % | 772 ms | 56,2 % | 0,463 |
| Whisper turbo, letra corroborada, CTC y FCPE por sílaba | 6,4 % | 151 ms | 55,8 % | 0,493 |
| La misma letra con GAME acotado a las sílabas | 6,4 % | 151 ms | 58,0 % | 0,522 |
| GAME libre, ensamble con los eventos vocales reutilizados en desarrollo | 6,4 % | 139 ms | 82,9 % | 0,554 |
| Worker real con separación nueva desde la mezcla | 6,4 % | 139 ms | 81,5 % | 0,558 |

La ejecución real de *Sigo aquí* duró 376,51 s en un Apple M4 con 16 GiB y otras inferencias concurrentes. Sus 432 notas puntuables cubrieron el 95,7 % del tiempo puntuable de la referencia. En el ensayo de desarrollo de *Go the Distance*, una letra independiente redujo el error de palabras de 21,8 % a 5,6 %. En el primer mapa reservado de Fito & Fitipaldis pasó de 8,5 % a 2,3 %. La mejora de letra dejó intacta la necesidad de revisar los ataques musicales. [Medición inicial y definición de métricas](generacion-local-2026-11-21.md)

Probamos seis umbrales entre 60 % y 95 % para que FCPE sustituyera el tono propuesto por GAME cuando el contorno parecía estable. En las dos canciones de desarrollo la exactitud por fotograma empeoró en las seis variantes. El desacuerdo sirve para dirigir la revisión. Desplazar toda la canción 50 ms aumentaba el F1 de *Sigo aquí* y empeoraba el de la grabación de Fito, de modo que se conserva el reloj original. La prueba de silencio rechazó el audio sin señal. Nueve cruces reales entre letras y grabaciones ajenas con metadatos falsamente coincidentes produjeron cero aceptaciones.

## Protocolo de validación

- **Muestra.** Veinte grabaciones en inglés de los paquetes Creative Commons publicados por UltraStar Deluxe y veinte en español con máster identificable de AllKaraoke. Los identificadores y las huellas se fijaron antes de evaluar las notas. Se comprobó la grabación y la sincronía de las ediciones originales. El conjunto inglés sobrerrepresenta a Jonathan Coulton por la distribución del catálogo disponible. Una edición etiquetada simultáneamente como catalana y española resultó ser catalana. Se reservó como control y se incluyó otra grabación cantada en español. [Muestra exacta](generacion-muestra.json)
- **Métricas.** WER de las palabras del mapa, p90 de la distancia absoluta del comienzo de las palabras coincidentes, clase tonal exacta por fotograma de 10 ms sobre todo el tiempo puntuable de la referencia y F1 de ataque con emparejamiento único, misma clase y tolerancia de 100 ms. Una octava de diferencia conserva la clase de nota. Los ataques que sobran o faltan penalizan el F1. Los fragmentos sin material cantado puntuable se identifican por separado.
- **Fragmentos.** El ensayo rápido extrae 24 s en el 40 % del intervalo admisible de cada mezcla, usando solo su duración. Para puntuar se recortan simétricamente 500 ms de los bordes. Este ensayo usa la transcripción del propio fragmento. Las letras completas recuperadas por título solo pueden corroborarse en las pruebas de grabación completa.
- **Objetivo de aprobación automática.** En una misma muestra evaluable, WER ≤5 %, p90 ≤120 ms, clase correcta ≥90 % y F1 ≥0,85. La comparación humana describe una referencia concreta y una elección de melodía principal. Un dueto, un rap o una voz de acompañamiento pueden admitir varias transcripciones musicalmente razonables. Hacen falta sesiones de canto a ciegas para medir la experiencia real de puntuación.
- **Reproducibilidad.** La matriz macOS procesa cuatro paquetes completos por máquina, con los mismos requisitos fijados y el mismo generador. Cada máquina recupera únicamente los paquetes que necesita y publica las métricas. Los audios, letras y mapas de referencia no se redistribuyen en los resultados. [Ejecución en macOS](https://github.com/AlexAmMo/karaoke/actions/runs/44899035944) · [Evaluador](../../scripts/benchmark_generation_corpus.py) · [Preparación de las ediciones](../../scripts/prepare_generation_validation.py)

Con Python 3.12 en el entorno de generación y FFmpeg en el PATH se pueden reproducir las pruebas. El segundo comando se ejecuta en el entorno de la app, que incluye los lectores del catálogo. Se requiere espacio para pesos e intermedios en el directorio privado elegido.

```sh
uv venv --python 3.12 build/chart-env
uv run --locked python scripts/prepare_generation_validation.py docs/validation/generacion-muestra.json build/private-recordings --language en
uv pip install --python build/chart-env/bin/python -r src/karaoke/generation_assets/requirements.txt
build/chart-env/bin/python scripts/benchmark_generation_corpus.py build/private-recordings/manifest.json build/private-scores --lookup-lyrics
```
