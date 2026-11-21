# Generar una canción puntuable a partir de su grabación

Karaoke ya puede analizar la mezcla original y producir un paquete UltraStar auditable. La voz del artista permanece en la reproducción. El separador, la transcripción y la estimación musical trabajan sobre una copia temporal. Un mapa generado empieza como borrador y requiere revisión para entrar en la biblioteca. La selección de canciones con un mapa comunitario verificado mantiene su flujo habitual.

## Resultados de la versión distribuida

La tabla cuenta cada grabación una vez dentro de su idioma. Las dos últimas filas vuelven a medir un pasaje de esos mismos temas. WER es la tasa de errores de palabra. La columna de inicio recoge la mediana de los p90 por canción sobre las palabras que coinciden con la referencia. La clase compara la nota cada 10 ms y el F1 exige que su ataque esté a ±100 ms del mapa humano.

| Conjunto | Grabaciones | WER | Inicio de palabra p90 | Clase correcta | F1 de ataques | Cumplen los cuatro objetivos |
|---|---:|---:|---:|---:|---:|---:|
| Canción completa, español (M4) | 20 | 9,75 % | 139,5 ms | 71,54 % | 0,610 | 0 |
| Canción completa, inglés (Windows x64) | 20 | 6,69 % | 73,5 ms | 78,79 % | 0,724 | 0 |
| Fragmento de 24 s, español (M4) | 20 | 6,93 % | 132,5 ms | 73,53 % | 0,648 | 0 |
| Fragmento de 24 s, inglés (Windows x64) | 20 | 6,34 % | 71,5 ms | 73,84 % | 0,705 | 0 |

| Objetivos por separado en canciones completas | Letra ≤5 % WER | Inicio p90 ≤120 ms | Clase ≥90 % | F1 ≥0,85 | Candidatas por la regla de confianza |
|---|---:|---:|---:|---:|---:|
| Canción completa, español (M4) | 6/20 | 6/20 | 1/20 | 1/20 | 0/20 |
| Canción completa, inglés (Windows x64) | 9/20 | 16/20 | 1/20 | 0/20 | 0/20 |

Ninguna de las cuarenta grabaciones completas superó el filtro previo de confianza que combinaba letra, coincidencia de tono y cantidad de notas dudosas. Con cero candidatas no se puede estimar el riesgo de aprobar mal una canción futura. La app mantiene la revisión antes de poner en la cola un mapa generado.

Los dos casos que se utilizaron para decidir una mejora también aparecen en los ensayos completos. Si se excluyen *Mr. Fancy Pants* y la grabación de la obra de Fito & Fitipaldis, quedan 19 muestras por idioma.

- En español, WER 10,53 %, p90 140,0 ms, clase 71,96 %, F1 0,609. Cumplen las cuatro metas 0/19.
- En inglés, WER 6,74 %, p90 76,0 ms, clase 78,78 %, F1 0,720. Cumplen las cuatro metas 0/19.

| Ocho grabaciones adicionales | WER | Inicio p90 | Clase correcta | F1 | Procedencia de la letra |
|---|---:|---:|---:|---:|---|
| Sigo Aquí | 6,39 % | 139 ms | 83,19 % | 0,557 | LRCLIB |
| Todo un hombre haré de ti | 11,54 % | 114 ms | 81,27 % | 0,532 | Transcripción del audio |
| Por la boca vive el pez | 2,33 % | 111 ms | 75,42 % | 0,792 | LRCLIB |
| Go The Distance | 5,56 % | 120 ms | 80,58 % | 0,594 | LRCLIB |
| Something | 0,00 % | 72 ms | 79,67 % | 0,691 | LRCLIB |
| Paramar | 17,39 % | 84 ms | 75,77 % | 0,675 | LRCLIB |
| Lose Yourself | 5,35 % | 53 ms | 55,16 % | 0,211 | LRCLIB |
| Stan | 24,80 % | 123 ms | 33,19 % | 0,078 | Transcripción del audio |

La muestra inglesa incluye once obras de Jonathan Coulton entre los veinte paquetes Creative Commons. Las ocho grabaciones adicionales incluyen siete obras distintas de las de la muestra principal. Los resultados describen estas ediciones y estos equipos. Las cifras individuales, los SHA-256 disponibles y la fuente de letra se conservan en el CSV. [Resultados por edición](generacion-resultados.csv) · [Ejecución de la versión definitiva en Windows](https://github.com/AlexAmMo/karaoke/actions/runs/44904428646)

### Subtítulos manuales de la grabación exacta

Al consultar los veinte ID de YouTube del conjunto español, los veinte respondieron y cuatro ofrecieron subtítulos manuales en español. La aplicación corroboró tres por coincidencia de palabras y reloj a lo largo de la canción. La cuarta, *Amorfoda*, conservó su transcripción. Las tres grabaciones corroboradas se volvieron a procesar con el texto de esos subtítulos y el mismo audio y modelos. Sus resultados con subtítulos son los que entran en la tabla principal.

| Canción | WER sin / con subtítulos | p90 sin / con | F1 de ataques sin / con |
|---|---:|---:|---:|
| La señora interesante | 22,11 % / 6,03 % | 181 / 139 ms | 0,557 / 0,562 |
| Estoy soñando | 6,96 % / 3,80 % | 149 / 154 ms | 0,671 / 0,671 |
| Monotonía | 13,21 % / 10,71 % | 149 / 148 ms | 0,593 / 0,605 |

Los tiempos de las frases de subtítulos sirven para verificar la edición. La alineación de las palabras y la melodía se calculan de nuevo sobre la voz. En el conjunto inglés se parte de las grabaciones y mapas publicados en los paquetes Creative Commons, sin un vídeo de YouTube asociado. [Comprobación de subtítulos de la app](../../src/karaoke/generation_assets/captions.py)

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

Se usaron *Sigo aquí* y *Go the Distance* para elegir el método de segmentación. Después se empleó una edición de *Por la boca vive el pez* para comparar el corrector de altura y *Mr. Fancy Pants* para comprobar una omisión detectada por el primer ensayo. La muestra principal incluye *Mr. Fancy Pants* y otra edición de la obra de Fito. Al interpretar el resultado final distinguimos esos dos casos del resto de las cuarenta grabaciones. Cada generador recibió audio y metadatos o una letra procedente de una fuente independiente. El comprobador abrió el mapa de referencia al calcular errores. No se corrigió el desfase de cada mapa para favorecer las métricas. Los borradores y las grabaciones permanecieron en directorios de trabajo privados.

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

La variante adicional de Tune Studio asignó un máximo acústico de comienzo silábico a cada sílaba cercana. Con una ventana de 300 ms, en *Go the Distance* bajó el p90 de 125 a 108 ms y elevó el F1 de 0,582 a 0,607. En *Sigo aquí* elevó el p90 de 139 a 150 ms para una mejora de F1 inferior a 0,002. En Fito pasó de 111 a 122 ms. No se adoptó como ajuste general del generador. En otra prueba se comprobó el perfil estándar con una vocal sintética afinada en la4 e intervalo sordo. Devolvió MIDI 69 y un evento sin puntuación, respectivamente.

Antes de revisar el conjunto retenido se definió una comprobación adicional de confianza para el modo automático. Se considera candidato un mapa con letra independiente corroborada al menos al 90 %, concordancia de clase entre los estimadores musicales de al menos el 88 % y un máximo del 15 % de notas marcadas para revisar. Se comparan por separado su cobertura y cuántos candidatos incumplen realmente alguno de los cuatro objetivos. Se trata de un experimento de calibración. La app requiere aprobación humana en todos los casos.

## Repetibilidad, memoria y corrección de tonos

GAME usa muestreo aleatorio durante la segmentación. Dos generaciones de la misma grabación podían producir barras distintas. Al fijar la semilla en 113 y crear una sesión de segmentación por canción obtuvimos tres huellas idénticas para los eventos de un fragmento real. Una cuarta ejecución con semilla 114 produjo otra huella. La semilla queda en el manifiesto. En el separador se conserva únicamente la salida vocal durante la suma de ventanas. En una mezcla estéreo de 24 s el máximo error absoluto de los 2.116.800 valores de muestra frente a las cuatro salidas de referencia fue cero. En una canción de cuatro minutos esto evita acumular unos 242 MiB de salidas estéreo que se iban a descartar.

Probamos también los pesos MIT de corrección musical de Nico Franke. Calculamos la afinación global del cantante, su distribución tonal en la nota y el contexto de las notas vecinas y del tono de la canción. La regla publicada permite desplazamientos de hasta dos semitonos cuando la probabilidad del modelo supera el umbral de 0,5. Usamos el modelo de alturas. El modelo independiente de finales redujo la cobertura correcta en las tres canciones de ensayo. La reproducción mantiene las duraciones obtenidas de la voz. [Código de los refinadores y características](https://github.com/ZerNico/tunestudio/blob/88d4fac5cb6df35c593cc16e730eddd10d96de39/training/src/tunestudio_training/pipeline/notefix.py) · [Pesos y evaluación del autor](https://huggingface.co/tuneperfect/tunestudio-note-refiners)

| Canción y referencia fijas | Clase antes / después | F1 antes / después | Notas cuyo tono cambió |
|---|---:|---:|---:|
| Sigo aquí | 82,9 % / 83,1 % | 0,554 / 0,551 | 12 |
| Go the Distance | 79,9 % / 80,3 % | 0,582 / 0,604 | 30 |
| Por la boca vive el pez | 70,3 % / 74,3 % | 0,747 / 0,777 | 48 |

Estas comparaciones usaron exactamente los mismos eventos y la misma letra antes y después del corrector. El F1 de *Sigo aquí* bajó dos milésimas mientras subió la clase por fotograma. Los tres ensayos miden el cambio del corrector respecto a su propia entrada.

## Primer conjunto retenido

Antes de fijar la semilla y aplicar el último corrector de tono se evaluaron 20 fragmentos por idioma. Cada uno dura 24 s y empieza en la posición definida por el protocolo. Cada celda es la mediana de la métrica calculada por grabación. El p90 es el p90 de cada fragmento antes de tomar la mediana. [Ejecución en Windows x64](https://github.com/AlexAmMo/karaoke/actions/runs/44899387367)

| Idioma | Grabaciones | WER | Inicio p90 | Clase correcta | F1 de ataques | Pasan todos |
|---|---:|---:|---:|---:|---:|---:|
| Español, M4 | 20 | 6,93 % | 133 ms | 71,75 % | 0,624 | 0 |
| Inglés, Windows x64 | 20 | 6,86 % | 74 ms | 69,52 % | 0,623 | 0 |

El mismo runner de Windows preparó los 79,45 s completos de *Mr. Fancy Pants* en 189 s incluyendo separación, ASR y construcción del mapa. Frente a esa referencia se obtuvo WER del 52,61 %, p90 de 59 ms, clase del 55,38 % y F1 de 0,496. El error pequeño de las palabras acertadas coexistió con muchas palabras ausentes o distintas. Una prueba de doce segundos con el perfil estándar generó asimismo un paquete con 38 notas. Cada ejecución en CI descarga los paquetes oficiales con sus créditos y verifica su identidad. Los trabajos distribuidos almacenan únicamente los resultados numéricos.

### Recuperación de un verso omitido

En la grabación completa de *Mr. Fancy Pants* el primer pase reconoció 104 palabras, frente a las 211 del mapa humano. La letra de LRCLIB describía la misma edición, pero con casi el doble de texto del que recogió Whisper. El generador vuelve a escuchar el audio en ventanas de 24 s con tres segundos de contexto en cada extremo cuando coinciden tres indicios previos. La identidad y la duración de la edición deben encajar, el texto candidato debe tener entre 1,25 y 2,6 veces la longitud del primer pase y debe contener, en orden, al menos el 85 % de lo que ya se oyó. Cada palabra del segundo pase pertenece a la ventana en la que cae su punto medio.

La letra externa se admite únicamente si el segundo pase aporta al menos un 20 % de palabras adicionales, su longitud queda entre 0,88 y 1,13 veces la de ese pase y el acuerdo ordenado supera el 85 %. Los casos que ya tienen una letra corroborada conservan un solo pase. Los casos sin indicios suficientes conservan su transcripción inicial.

| Misma grabación, mismo modelo | Palabras reconocidas | WER de ASR | Acuerdo con la letra recuperada |
|---|---:|---:|---:|
| CPU, pase completo | 104 | 53,08 % | Insuficiente |
| CPU, ventanas de 18 s | 204 | 8,53 % | 96,3 % |
| CPU, ventanas de 24 s | 203 | 6,64 % | 98,0 % |
| Apple Metal, ventanas de 24 s | 203 | 6,16 % | 98,5 % |

La letra recuperada por ambos dispositivos tuvo WER del 6,64 %. El rescate mantiene la condición de borrador. Las palabras que conservan las dos transcripciones no certifican la melodía ni el resto de la letra. Las cifras proceden de un caso seleccionado por el fallo observado en la primera tanda. Deben considerarse una regresión corregida y una prueba de que se puede recuperar un verso omitido.

### Independencia del evaluador

Al preparar el corpus se verifican los paquetes que se usarán como referencia. Al generar solo se entregan audio, idioma, artista, título y, cuando proceda, letra externa corroborada. Para evaluar se guarda primero el borrador, se calcula su SHA-256 y entonces se abre el mapa humano. Como control adicional se prohibió durante la inferencia abrir los dos ficheros de referencia mediante un auditor de acceso de Python. En la primera comparación se usó el mapa real. En la segunda se desplazaron sus notas cinco semitonos. Ambas inferencias generaron las mismas 63 notas y la misma huella `ca26c201a9cc3603325937dd8f665b56ccd3254bbee834cad08e724def8b13bd`. Con el mapa real se obtuvo clase correcta del 74,79 % y F1 de 0,682. Con la referencia alterada se obtuvo 0,61 % y 0,016.

El reloj de transcodificación también se comprobó por separado. Una mezcla real de 24 s se codificó como Opus en WebM y se procesó con el paso a MP3 del generador. Al decodificar a 8 kHz había el mismo número de muestras. En ventanas a los 2, 12 y 20 s la correlación superó 0,999 y el retardo medido fue 0 ms. Esta medición cubre ese flujo de códecs y equipo.

El runner público de GitHub intentó obtener un máster español por el identificador exacto de YouTube. YouTube exigió autenticación de la máquina y el trabajo se detuvo. El corpus español se procesa en el Mac que sí pudo obtener las grabaciones. Se conservan dos comprobaciones de identidad, SHA-256 del archivo y SHA-256 de todas las muestras PCM a 44,1 kHz estéreo de 16 bits. El conjunto público de resultados contiene identificadores, huellas y medidas. [Prueba de origen del runner](https://github.com/AlexAmMo/karaoke/actions/runs/44900526573) · [Resultados por grabación](generacion-resultados.csv)

Se contrastaron las huellas SHA-1 de los 48 mapas evaluados con los 2.805 títulos y huellas publicados en las particiones de Tune Studio. Ningún fichero era idéntico. En la muestra principal de cuarenta no se identificó la misma interpretación por artista y título. Entre los títulos relacionados figura *She Wolf*, la versión inglesa de *Loba*. En los ocho casos adicionales, *Something* figura en entrenamiento, *Go the Distance* figura con otro intérprete y *Lose Yourself* figura en la partición de prueba de Tune Studio. El control de acceso al mapa durante nuestra inferencia y esta comparación de títulos cubren riesgos diferentes. Otros modelos usan colecciones de preentrenamiento más amplias. [Manifiesto publicado por Tune Studio](https://github.com/ZerNico/tunestudio/blob/88d4fac5cb6df35c593cc16e730eddd10d96de39/training/splits/manifest.json)

Los ocho paquetes adicionales incluyen otra edición de *Por la boca vive el pez*, que también aparece en la muestra principal. Comparten las 438 notas al aplicar 73 ms de desfase a los mapas. Las grabaciones presentan 36,25 ms de diferencia por correlación a los 25, 130 y 240 s (correlaciones de 0,980 a 0,988). Al comparar directamente los mapas de la comunidad el F1 de ataques es de 0,998 y la clase por fotograma del 58,53 %. Corrigiendo únicamente el desfase de las grabaciones, estas cifras son 1,000 y 79,62 %. Se conservan las métricas con el reloj original de cada edición al medir el generador. La segunda edición cuenta como prueba de versión de la misma obra, no como otro tema musical.

### Distinguir rap y melodía

En *Lose Yourself* la edición humana deja 706 notas en estilo libre y puntúa 315. Comparamos la mezcla y la voz separada con YAMNet, que distingue habla, canto y rap en ventanas de 0,96 s. Sobre la mezcla, su etiqueta de rap con umbral 0,30 solo identificó el 0,7 % de las notas de estilo libre. Sobre la voz aislada, una regla más estricta (habla ≥0,85 y superior al doble de la señal de canto) identificó el 52,3 % del estilo libre, pero también quitó la altura del 34,9 % de las notas que el mapa sí puntúa. El F1 pasó de 0,211 a 0,228 y la clase correcta bajó del 55,12 % al 35,77 %. Aplicada a otras seis canciones melódicas, esa misma regla retiró entre el 4,3 % y el 47,5 % de las notas humanas. En *Stan* discriminó mejor entre habla y melodía (92,8 % de estilo libre detectado, 1,2 % de notas puntuables marcadas). El comportamiento dependía de la interpretación. Este clasificador se queda en el experimento y los pasajes dudosos siguen siendo revisables en el editor. [Modelo y clases de YAMNet](https://github.com/tensorflow/models/tree/master/research/audioset/yamnet) · [Conversión ONNX usada en el ensayo](https://huggingface.co/audiomagic/yamnet-onnx/tree/f25b741c2f0bdc6d7e6db24b5fddda23347dbafd)

### Otra medición independiente de los ataques

Probamos el modelo ONNX de Spotify Basic Pitch sobre la voz separada de ocho grabaciones completas. Tardó entre 5,2 y 16,0 s por tema en un núcleo del M4. En cada nota del borrador buscamos un ataque de Basic Pitch a ±100 ms, solapado en el tiempo y con amplitud estimada de al menos 0,6. Sustituir el tono por el del otro modelo redujo la clase correcta del 82,90 % al 82,78 % en *Sigo aquí* y del 77,17 % al 71,71 % en *Go the Distance*, usando los borradores del ensayo previo. Al conservar únicamente las notas en las que ambos modelos coincidían en ataque y altura, la precisión respecto al mapa era del 65,70 % en *Sigo aquí* y del 56,85 % en *Go the Distance*. En *Something* alcanzó el 86,54 % y en *Paramar* el 88,04 %. La coincidencia entre ambos estimadores tampoco bastó para publicar automáticamente ni siquiera esa parte del mapa. [Basic Pitch, modelo y código de inferencia](https://github.com/spotify/basic-pitch/tree/fa5997af0a8210982619003269994a1be25eddf3/basic_pitch)

### Canciones largas con letra densa

La primera ejecución de *Stan* (8 min 16 s) alcanzó el límite protector de 240 millones de celdas de historial del alineador CTC. La ruta definitiva conserva estados intermedios y reconstruye las decisiones de cada bloque hacia atrás. Calcula el mismo camino global y usa el reloj de toda la actuación. Las pruebas de repeticiones, empates y tres matrices de emisiones reales coincidieron en todos sus frames con el algoritmo original. En un fragmento de 24 s forzamos esta ruta con un límite artificial de una sola celda: las 63 notas y la huella del TXT completo coincidieron con la ejecución habitual.

El CLI de producción procesó el M4A de *Stan* durante 656,24 s en el M4 con otro trabajo activo. La ruta densa completó una matriz de 295.398.596 celdas con unos 7,2 MiB para sus checkpoints y el bloque de decisiones. El paquete contenía 1.758 notas, se pudo leer con el importador y mantuvo la duración del original dentro de un microsegundo. El WER fue del 24,8 %, el p90 de inicios de 123 ms, la clase correcta del 33,19 % y el F1 de 0,078. Su referencia puntúa la altura en 256 notas y deja 1.104 de estilo libre. El generador propuso altura en 1.746 notas, de modo que la revisión resulta especialmente importante en rap y diálogo. [Reconstrucción exacta por bloques](../../src/karaoke/generation_assets/dense_alignment.py)

### Estribillos repetidos

En *Lose Yourself*, el comparador inicial se anclaba a otra aparición del mismo estribillo. Devolvía un 67,3 % de acuerdo aunque, en el orden real de la canción, la letra externa y la transcripción alcanzaban el 90,6 %. Mantenemos el comparador original para las ediciones que ya corrobora. Si falla, una segunda comparación calcula la subsecuencia común más larga. Exige identidad de artista y título, hasta cuatro segundos de diferencia de duración, un mínimo de 96 palabras reconocidas, longitud del texto entre el 94 % y el 106 % de la transcripción, coincidencia total del 90 % y al menos el 84 % en cada tercio. Los tercios conservan su posición en ambas letras. La decisión solo usa transcripción, edición y palabras externas.

En 28 grabaciones completas con transcripciones guardadas (20 de la muestra española y ocho casos adicionales), la única nueva elección fue la edición de *Lose Yourself* a 0,26 s de la duración real. Los acuerdos por tercio fueron del 90,3 %, 88,5 % y 91,9 %. Al simular que otras obras tenían los mismos metadatos, la regla rechazó los 887 cruces. También rechazó 168 alteraciones construidas al borrar, repetir, invertir o permutar estrofas enteras. Estos ensayos cubren cambios sustanciales. Unas pocas palabras distintas pueden cumplir los umbrales y siguen formando parte de la revisión humana. [Pruebas del comparador y del rescate de versos](../../tests/test_generation_worker.py)

Los 20 fragmentos ingleses repetidos en Windows con la semilla fijada y el corrector dieron medianas de WER del 6,34 %, p90 de 71,5 ms, clase del 73,84 % y F1 de ataques de 0,705. Ninguno superó simultáneamente los cuatro objetivos. En la ejecución anterior el F1 mediano era de 0,623. Cambiaron la segmentación reproducible, el corrector y las máquinas virtuales del ensayo. Las comparaciones por nota sobre entradas idénticas de la sección anterior aíslan el efecto del corrector. [Medición de 20 canciones completas y sus fragmentos en Windows](https://github.com/AlexAmMo/karaoke/actions/runs/44900471775)

Al volver a generar el mapa completo de *Lose Yourself*, los errores de palabra bajaron de 106 a 45 sobre 841 (WER del 12,60 % al 5,35 %). El borrador nuevo obtuvo p90 de 53 ms, clase correcta del 55,16 % y F1 de ataques de 0,211. La corrección recupera letra en estrofas repetidas. Los límites musicales concretos del rap permanecen en las cifras de la misma grabación.

En la matriz posterior de Windows, *Mr. Fancy Pants* fue la única de las 20 canciones que activó la segunda escucha por ventanas. El mapa generado alcanzó WER del 6,64 %, p90 de 57 ms, clase correcta del 79,04 % y F1 de ataques de 0,753. En el ensayo inicial de esa misma grabación eran 52,61 %, 59 ms, 55,38 % y 0,496, respectivamente. Entre ambas ejecuciones también se fijó la semilla y se incorporó el corrector de altura. El cambio de letra tiene además el ensayo controlado con el mismo reconocedor que aparece más arriba. [20 grabaciones independientes procesadas con rescate por ventanas](https://github.com/AlexAmMo/karaoke/actions/runs/44902083197)

La misma segunda escucha también puede descartar una edición. En *Como la flor* había letras de 171 palabras para grabaciones situadas a menos de dos segundos del máster y el primer pase reconoció 132. El segundo pase no corroboró la ampliación. El generador conservó el borrador transcrito del audio, que obtuvo un WER del 30,43 % respecto a los 138 términos de su mapa humano.
