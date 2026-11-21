# Elegir la letra por evidencia acústica

Este ensayo compara dos textos ya existentes para cada una de las cuarenta grabaciones de desarrollo: la letra del mapa base y la transcripción completa de Qwen. No crea letras mediante una referencia humana ni ejecuta de nuevo los reconocedores. La hipótesis es que un alineador acústico independiente podría escoger la transcripción mejor respaldada por la grabación, incluso cuando Qwen empeora el resultado global al usarlo siempre.

**Resultado:** la regla primaria mejora seis canciones y empeora cuatro, sin aumentar los casos con WER ≤5 % o ≤1 %. Ninguna regla demuestra una mejora general suficiente para sustituir la letra actual ni alcanza fiabilidad casi perfecta. Las cuatro se conservan como resultados experimentales, sin modificar producción.

## Método fijado antes de la evaluación

Se reutilizan las emisiones de Sylla-600M ya calculadas sobre las mezclas exactas. Su ficha describe un modelo de alineación con salidas para voz principal y coros; no garantiza que una probabilidad mayor identifique el texto más correcto. [Ficha original de Sylla](https://huggingface.co/radiant-lyrics/sylla-600m-v1/tree/0a228acf0c1351ad0e2734604ee921d497d861e8).

La probabilidad CTC de una secuencia suma las probabilidades de todos los caminos temporales que producen ese texto después de eliminar blancos y repeticiones consecutivas. Es distinta de escoger solamente un camino de alineación. [Definición original de Graves y colaboradores, secciones 3–4](https://www.cs.toronto.edu/~graves/icml_2006.pdf) · [Contrato de CTCLoss de PyTorch](https://docs.pytorch.org/docs/2.15/generated/torch.nn.CTCLoss.html).

Se fijaron cuatro reglas: cabeza principal (`lead`) o promedio probabilístico de principal y coros (`pooled`), normalizadas por número de fotogramas o por número de caracteres del candidato. La regla primaria declarada es `lead-frame`; los cuatro resultados se publican sin escoger una regla después de ver las referencias. Normalizar por fotogramas conserva el orden de la probabilidad total dentro de una misma canción; normalizar por caracteres prueba una compensación de longitud distinta. Ninguna normalización es una garantía de exactitud de palabras.

Se aplica NFKC y minúsculas, se conservan los apóstrofos y se representan las separaciones entre palabras con `|`. La puntuación retirada se registra. No se eliminan silenciosamente letras o números desconocidos: un carácter no representable invalida la comparación. Un candidato vacío, de menos de doce palabras o sin camino finito conserva la base. Qwen debe contener al menos el 78 % de las palabras de la base, reutilizando el límite inferior ya empleado en `generation_worker.choose_candidate`; así no se premia una transcripción casi vacía. No hay límite superior, pues puede recuperar palabras omitidas. Los empates también conservan la base.

Los cachés conservan 113 columnas del vocabulario después del softmax global, en float16. Se usan sus valores almacenados y no se redistribuye la masa de las columnas excluidas. `pooled` es el logaritmo del promedio de las probabilidades de ambas cabezas, no el promedio de sus logaritmos. La suma CTC posterior emplea float64; sigue siendo un cálculo sobre emisiones previamente cuantizadas, no una reproducción de logits nuevos de precisión completa.

## Memoria y comprobación matemática

La primera implementación usaba `torch.ctc_loss`. Antes de procesar canciones se sustituyó por la misma recurrencia de suma con filas rodantes de NumPy: memoria proporcional al texto, en vez de guardar toda la matriz tiempo × texto. La retícula de la canción mayor habría necesitado unos 260 MiB, más PyTorch. El recorrido nuevo no carga Torch, modelos, GPU ni audio.

La prueba sintética enumera todos los caminos de cuatro fotogramas y cuatro clases, incluida una clase omitida de la matriz retenida. El resultado coincide con la recurrencia a 1e-12 para cuatro objetivos, incluidos caracteres repetidos; también comprueba texto vacío, camino imposible y caracteres no representables. El piloto de coste eligió la grabación con mayor retícula estimada, no por su referencia. Procesó esa canción completa en 4,62 s, con RSS máximo de 47.874.048 bytes (45,7 MiB) y cero swaps.

La tanda completa procesó **40/40 canciones y congeló 160 decisiones/textos el 21-11-2026 a las 19:06:28 UTC**, antes de evaluar. Tardó 68,79 s, con máximo residente de 48.300.032 bytes (46,1 MiB), un proceso CPU y cero swaps. No hubo candidatos inválidos ni ausencias. La canción del piloto reprodujo exactamente sus cuatro probabilidades y textos en la tanda. Los registros son `pilot-v1.log` y `full-v1.log`, bajo `build/generation-next/lyrics-acoustic/`.

## Resultados completos

Las cifras de WER son medianas por canción. «Mejora/peor/igual» compara cada canción con su misma base; no suma variantes distintas ni elige una por referencia.

| Regla | WER total | WER ES | WER EN | Mejora / peor / igual | Casos ≤5 % | Casos ≤1 % | Elige Qwen |
|---|---:|---:|---:|---:|---:|---:|---:|
| Base | 6,72 % | 7,88 % | 5,63 % | 0 / 0 / 40 | 17 | 4 | — |
| Qwen siempre | 14,49 % | 17,48 % | 10,80 % | 9 / 30 / 1 | 7 | 0 | 40 |
| `lead-frame`, primaria | 6,72 % | 8,78 % | 4,75 % | 6 / 4 / 30 | 17 | 4 | 10 |
| `lead-character` | 6,72 % | 6,82 % | 5,63 % | 5 / 2 / 33 | 17 | 4 | 7 |
| `pooled-frame` | 10,62 % | 9,84 % | 10,80 % | 5 / 11 / 24 | 15 | 3 | 16 |
| `pooled-character` | 8,13 % | 10,62 % | 5,94 % | 4 / 5 / 31 | 16 | 4 | 9 |

La regla primaria recupera una transcripción mejor en «Monkey Shines» (WER 14,63 % → 4,88 %), pero elige una peor en «Amorfoda» (1,38 % → 32,41 %). Mantener la mediana global no equivale a conservar la calidad de cada canción. La alternativa normalizada por caracteres evita algunas regresiones, pero todavía empeora dos grabaciones y no añade casos dentro de los umbrales. No se selecciona esa variante retrospectivamente como un éxito general.

La base contiene letras corroboradas de otras fuentes; Qwen y la puntuación CTC son observaciones acústicas distintas, no verificaciones de corrección humana. Una probabilidad acústica mayor no garantiza el texto correcto de la edición. Tampoco se han combinado aquí fragmentos de ambos candidatos: cada regla escoge un texto completo.

El [CSV de 240 filas](generacion-letra-acustica-2026-11-21.csv) contiene las cuarenta grabaciones de cada una de las seis filas de la tabla, con métricas y hashes, sin letras. SHA-256 del CSV: `f86210471220b7735645b0fb4ea80614685bc406fa2ca8a7d448503ffe4bfd9a`. La evaluación completa se conserva en `full-v1-evaluation.json`, SHA-256 `f7d3fc7a88ee32dc870a9798f9fbbdd6d01d88815637984ece8a9502cd28df0d`; `export_results.py` conserva la transformación de JSON a CSV.

## Procedencia y reproducción

[lyrics_acoustic_selection.py](../../scripts/experiments/lyrics_acoustic_selection.py) separa `generate` de `evaluate`. La generación sólo acepta el manifiesto de identidades, mapas predichos, texto Qwen y emisiones; no tiene entrada de mapas de referencia. Comprueba las huellas del máster, los modelos Sylla, la base y la salida Qwen. Cada decisión y texto elegido se guarda con SHA-256, y después se congela la cohorte. La evaluación verifica esa congelación antes de abrir las referencias de la misma grabación.

```sh
build/generation-bench/env/bin/python scripts/experiments/lyrics_acoustic_selection.py selftest
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 build/generation-bench/env/bin/python scripts/experiments/lyrics_acoustic_selection.py generate --identities docs/validation/generacion-muestra.json --charts build/generation-v3/lyrics/final/charts.json --qwen build/generation-next/qwen/mix-full-v1 --emissions build/generation-v3/timing/sylla --output build/generation-next/lyrics-acoustic/full-v1
build/generation-bench/env/bin/python scripts/experiments/lyrics_acoustic_selection.py evaluate --identities docs/validation/generacion-muestra.json --corpus build/generation-v2/corpus.json --predictions build/generation-next/lyrics-acoustic/full-v1 --output build/generation-next/lyrics-acoustic/full-v1-evaluation.json
```

La salida no se sobrescribe. El adaptador exacto se conserva en `build/generation-next/lyrics-acoustic/source-at-generation-v1.py`; el plan registra su hash, el de `songs.py`, la versión de NumPy, las guardias y la prueba matemática. El modelo Sylla corresponde a la revisión `0a228acf0c1351ad0e2734604ee921d497d861e8`, pesos principales SHA-256 `bc8d8e504eabec5538027623b376e3f560691c2fb134c1a8fc6081bd10e86716` y cabeza secundaria `c6d939babc45e1770a9bdd7d12a811eecf7fcd82006163c50cd343d0856f7e9f`.

Huellas adicionales: adaptador `3ee559e63abd9a892b3ae6f8f2357ee43737e6e2513e1464444306840db1c0bf`; plan `abb8363a291f33fae88b437f4159eb6b8e1d2e9a7ac2167cbc9dc108853c3ee3`; congelación conjunta `bca8cadbbc0b266cb892539314ecb41a96936207ac8fc838c815522ab4565236`.

`source-snapshot/` conserva también los módulos de lectura y métricas. Su manifiesto, creado después de evaluar, vincula esos bytes y el exportador al JSON de resultados; verifica que el generador y el lector siguen coincidiendo con las huellas del plan previo. No se presenta esa copia posterior como una nueva decisión predeclarada.

Los resultados de palabras no constituyen medidas de alineación, altura ni duración de notas. Las cuarenta canciones son desarrollo y regresión, no una reserva independiente. No se modificó la aplicación ni se incorporó Sylla a sus instaladores.
