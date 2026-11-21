# Finales de nota por acuerdo de SOME y ROSVOT

El consenso acorta **283 notas de 39 canciones** y retira 29,05 s: 22,892 s que no coincidían con la clase puntuable humana y 6,158 s que sí coincidían. La precisión mediana apenas sube del **50,260 % al 50,365 %**, mientras el acierto de clase sobre la referencia baja del 76,475 % al 76,170 %. **Ninguna de las cuarenta canciones supera las cinco puertas ni el objetivo de fiabilidad casi perfecta**, antes o después. El ensayo no justifica incorporarlo a producción.

## Regla fijada antes de medir

Se ejecutó un único brazo, descrito previamente en [el diagnóstico del ensamblado](generacion-game-ensamblado-2026-11-21.md), además del control base. Para cada barra puntuable, cada transcriptor ofrece un evento de la misma clase cromática con ataque a ±80 ms. El emparejamiento recorre las barras en orden, escoge el ataque más próximo, desempata por índice y no reutiliza eventos ni retrocede dentro de una clase.

La barra se acorta sólo si ambos finales están antes del final existente, difieren como máximo 40 ms y el posterior deja al menos 80 ms desde el ataque de la barra. Se usa ese final posterior, redondeado a la rejilla del mapa, y se conserva la barra si el redondeo no permite un acortamiento válido. No se añade un límite retrospectivo al recorte ni se seleccionan variantes por su resultado. Letra, altura, ataque, número de notas y barras libres permanecen intactos.

Las reglas de energía, recorte proporcional y final de grafema ya ensayadas no se repiten aquí. Esta regla contrasta los finales de dos transcriptores musicales cuyos eventos estaban calculados. Tampoco supone que el acuerdo entre modelos equivalga a corrección humana: ambos observan la misma pista vocal separada.

## Identidad y congelación

Se conservan las mismas **40 grabaciones completas**, veinte por idioma. Antes de generar se comprobaron los SHA-256 reales de los másteres y las voces, su reloj de 44.100 Hz, la duración y que SOME y ROSVOT apuntaban al mismo WAV en cada canción. Los eventos debían tener tiempos finitos, positivos y ordenados, sin solapamiento, y conservar los modelos y ventanas del ensayo anterior.

Trece voces se vinculan al máster mediante los manifiestos del runner. Otras veintiséis usan las huellas locales previamente verificadas y su índice de preparación; la restante tiene un manifiesto local con las huellas de máster y voz. No se inventó una huella ausente en los JSON de eventos ni se sustituyó por la de otra separación inglesa. La huella actual se comparó con su procedencia correspondiente. El plan conserva esa distinción y los hashes de todos los insumos.

El plan se escribió antes de producir candidatos y los cuarenta resultados se congelaron antes de abrir las referencias. Se utilizaron el evaluador común, sus cinco puertas y su objetivo estricto `--near-perfect`, sin cambios. Hubo **40/40 pares evaluados, cero ausencias y cero mapas inválidos**; las ausencias habrían permanecido en el denominador cuarenta.

## Resultados completos

Las siguientes cifras son medianas por canción, salvo los recuentos de aprobación.

| Medida | Base | Consenso |
|---|---:|---:|
| WER | 6,715 % | 6,715 % |
| p90 de inicio de palabra | 107 ms | 107 ms |
| Clase correcta sobre referencia | 76,475 % | 76,170 % |
| Precisión del tiempo solicitado | 50,260 % | 50,365 % |
| Cobertura de tiempo humano | 96,045 % | 95,860 % |
| F1 de ataque y altura | 0,66770 | 0,66770 |
| F1 de ataque, altura y final | 0,08545 | 0,08670 |
| Error absoluto de final, p50 | 122,95 ms | 121,60 ms |
| Error absoluto de final, p90 | 226,25 ms | 224,40 ms |
| Cinco puertas | 0/40 | 0/40 |
| Objetivo casi perfecto | 0/40 | 0/40 |

La precisión mejora en 35 canciones, empeora en tres y queda igual en dos; la mediana de las diferencias por canción es +0,11 puntos porcentuales. Las tres regresiones son «Lamento boliviano» (−0,05 puntos), «Heaven Can't Wait» (−0,08) y «Code Monkey» (−0,04). El acierto sobre todos los fotogramas humanos baja en 32 y queda igual en ocho: recortar conserva alturas, pero puede retirar canto correcto. El F1 que exige también el final mejora en 23 y queda igual en diecisiete. Ninguna nota cambia en «Estoy soñando».

| Grupo | Notas acortadas | Precisión mediana, base → consenso | Clase sobre referencia, base → consenso | Tiempo incorrecto retirado | Canto correcto perdido |
|---|---:|---:|---:|---:|---:|
| Español, 20 | 157 | 49,930 % → 49,995 % | 71,535 % → 71,310 % | 11,437 s | 3,480 s |
| Inglés, 20 | 126 | 50,770 % → 50,990 % | 78,790 % → 78,670 % | 11,455 s | 2,679 s |

De los 22,892 s incorrectos retirados, 3,831 s tenían otra clase humana y 19,060 s no tenían una nota humana puntuable. Esta partición integra los intervalos continuos sólo para explicar lo retirado; no modifica las métricas comunes. Un intervalo sin nota humana no demuestra silencio acústico. La hipótesis obtiene apoyo parcial: retira más error que canto correcto y mejora algunos finales. Su efecto es demasiado pequeño para resolver las prolongaciones y acarrea regresiones.

El [CSV de ochenta filas](generacion-finales-consenso-2026-11-21.csv) publica ambos brazos completos, métricas, recortes y hashes, sin letras. No se selecciona retrospectivamente la mejor salida por canción.

## Comprobaciones y reproducción

[consensus_releases.py](../../scripts/experiments/consensus_releases.py) separa `plan`, `generate` y `evaluate`. Sus controles sintéticos comprueban emparejamiento sin reutilización, equivalencia de octava, elección del final posterior, duración mínima, conservación de freestyle y que un final redondeado al mismo tick no se cuente como cambio. Una comprobación adicional sobre los cuarenta mapas confirmó que sólo cambian las duraciones autorizadas. No se importó Torch, cargaron modelos ni usaron GPU o reproducción de audio. La fase de generación y congelación de v2 tardó 1,42 s, con los cachés disponibles.

Antes de evaluar se detectó un defecto de conteo: dieciséis propuestas redondeaban al tick original y se contaban por diferencias flotantes de aproximadamente 10⁻¹⁴ s. Una prueba pequeña falló antes de la corrección y pasó después. Se preservaron v1 y su adaptador, se congeló v2 y se comprobó que sus **cuarenta TXT son idénticos byte a byte**. Sólo cambió el conteo de propuestas efectivas, de 299 a 283; no cambió el candidato ni se consultó la referencia para corregirlo.

```sh
uv run python scripts/experiments/consensus_releases.py selftest
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 uv run python scripts/experiments/consensus_releases.py plan
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 uv run python scripts/experiments/consensus_releases.py generate
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 uv run python scripts/experiments/consensus_releases.py evaluate
```

Los comandos rechazan sobrescribir resultados. Para repetir se debe proporcionar el mismo `--output` nuevo a las tres fases. La evidencia reside en `build/generation-next/consensus-releases/v2/`: `source-at-generation.py`, `plan.json`, `decisions.json`, `frozen.json`, las dos evaluaciones y `analysis.json`. `summarize.py` conserva la transformación posterior de resultados a CSV y el diagnóstico del tiempo retirado; no genera candidatos. Ruff y la comprobación de espacios pasan.

SHA-256 del plan: `6b2d9e0481a408f2c21cf1f32031907b6bcaf12a1736b210e63b52761db369b0`; congelación conjunta: `f928f675fb7972759a218e3943f552dc76f2751ea95eec64879620c4a8f9efc6`; CSV: `95056dbf55e7b863e2a6a7d7c8a9983288c3ecfa67d977cd88853e9d053c1eed`. Las evaluaciones tienen hashes `bb1d9e37fc24fbe26b8a130d2fc25b2e0d342237a8d0a164f9a774a6433925d8` (base) y `9916794157dbba8ca1ef09e8efe0d13fd8ba8c27f242feb77cec283754d74da5` (consenso).

Estas canciones son desarrollo y regresión, no una muestra independiente de todo YouTube. Se conservaron los informes anteriores, producción y los controles de admisión.
