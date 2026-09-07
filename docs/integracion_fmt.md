# Estudio de integración FMT en intervals_fit_analytics

Fecha: 2026-09-07. Estado: propuesta técnica; no implementada.

## Conclusión

Es viable añadir un panel experimental de variabilidad conjunta utilizando los datos diarios que el proyecto ya consulta. Recomiendo conservar CTL/ATL/TSB y mostrar por separado el nuevo análisis, su cobertura y sus variables originales. La prioridad es normalizar el historial y corregir sus límites temporales antes de calcular matrices.

El [artículo de Gabriel Della Mattia](https://medium.com/@gdellamattia/fmt-tensor-multidimencional-funcional-60f126fd1197), leído completo desde el navegador, propone una matriz de covarianza de variaciones fisiológicas, su traza y autovalores, y un Transformer para interpretar secuencias. No proporciona en el texto una especificación reproducible de normalización, ventanas, faltantes, entrenamiento ni validación predictiva. La definición operativa que sigue es una propuesta propia inspirada en esa idea; no reproduce el algoritmo de ednaLab.

## Interpretación matemática

La diagonal de una covarianza contiene varianzas; su traza suma esas varianzas. Véase la [documentación de NumPy](https://numpy.org/doc/stable/reference/generated/numpy.cov.html). Por tanto, una traza alta indica variabilidad conjunta elevada en las escalas elegidas. Identificarla con curvatura geométrica, agotamiento o estrés no compensado requiere hipótesis y validación adicionales.

Un autovalor dominante indica una dirección de variación dominante. Esa dirección puede combinar todas las variables; no demuestra una alteración de un órgano o músculo. Los autovectores permiten mostrar qué variables participan, sin atribuir causalidad. Una traza baja tampoco implica recuperación: valores persistentemente desfavorables pueden variar poco.

No estandarizar cada variable dentro de la misma ventana cuya covarianza se calcula: si todas quedan con varianza uno, la traza se convierte en el número de variables y pierde la señal buscada. Tampoco mezclar directamente milisegundos, pulsaciones, horas y carga: sus escalas dominarían arbitrariamente el resultado.

## Datos y API disponibles en el código

Rutas relativas a la URL base configurada. Son los contratos utilizados por el cliente local, no una verificación en vivo del servicio. Se usa HTTP Basic con usuario `API_KEY` y la clave configurada; no es necesaria ninguna credencial nueva para este diseño.

| Método de `IntervalsClient` | GET | Uso propuesto |
|---|---|---|
| `get_wellness` | `athlete/{athlete_id}/wellness`, parámetros `oldest`, `newest` | HRV, reposo, sueño y variables subjetivas |
| `get_activities` | `athlete/{athlete_id}/activities`, mismos parámetros | Carga diaria y características de las sesiones |
| `get_activity_details` | `activity/{activity_id}` | Contexto y metadatos de una sesión |
| `get_activity_streams` | `activity/{activity_id}/streams` | Potencia, FC, temperatura y tiempos |
| `get_activity_power_curve_csv` | `activity/{activity_id}/power-curve.csv` | Mejores esfuerzos por duración |
| `get_athlete_power_curves` | `athlete/{athlete_id}/power-curves` | Referencias históricas de potencia |

Archivos: [cliente](../src/intervals_api.py), [wellness](../src/wellness_hrv.py), [carga](../src/load_metrics.py), [FIT](../src/fit_analyzer.py), [potencia](../src/power_peaks.py).

| Variable | Disponibilidad en el código | Tratamiento |
|---|---|---|
| HRV diaria | `hrv_rmssd` en wellness; `hrv` en el historial HTML | Confirmar métrica/dispositivo; logaritmo solo para RMSSD positivo |
| FC de reposo | `resting_hr` | Conservar fecha real y precisión |
| Sueño | `sleepSecs` convertido en `sleep_hours` | Convertir unidades sin redondear antes del cálculo |
| Carga | `icu_training_load` o `training_load` | Sumar sesiones por día; registrar origen, sin asumir que toda carga es TSS de potencia |
| Fatiga, dolor, estrés, ánimo | Se extraen en wellness; el HTML conserva el registro seleccionado | Mantener también historial y documentar la escala antes de incluirlos |
| CTL/ATL/TSB | API wellness y cálculo local separado | Contexto; excluir del vector inicial por redundancia con carga |
| Temperatura | FIT y streams | Contexto de sesión; no asumir que es temperatura corporal |
| Potencia y FC de esfuerzo | FIT y streams | Resúmenes de sesión, separados del pulso de reposo |
| W′ balance | No implementado en los módulos revisados | Requiere CP, W′ y modelo de recuperación explícitos |
| Curva autonómica de 24 horas | No existe en la ingesta revisada | La HRV diaria no permite reconstruir la curva intradiaria mostrada en el artículo |

La existencia de un campo en el código no demuestra que todos los atletas tengan datos. Falta una auditoría de cobertura real por atleta, dispositivo y fecha.

## Problemas que resolver primero

1. `recopilar_datos_salud_y_carga` en [interactive_profile.py](../src/interactive_profile.py) consulta hasta `fecha_ref + 1 día` y construye el historial con toda la respuesta. Si no hay registro anterior, selecciona el último disponible. El nuevo cálculo debe filtrar estrictamente por fecha de corte y rechazar registros futuros.
2. Las medias de siete días actuales usan las últimas siete observaciones válidas, que pueden abarcar más de una semana. Reindexar a calendario diario y diferenciar días de observaciones.
3. El historial HTML omite las series subjetivas y la carga diaria; además redondea HRV y sueño. Construir la tabla analítica desde los datos originales, antes de preparar la presentación.
4. `get_activities` y `get_wellness` pueden devolver listas vacías ante errores HTTP. Distinguir error de consulta, día sin registro y descanso confirmado. Solo el último admite carga cero.
5. El cálculo local usa `ewm(span=42/7)`. Pandas define `alpha=2/(span+1)`, que no equivale a fijar constantes de decaimiento de 42/7 días. Documentar la convención antes de comparar con CTL/ATL de la API; también fijar inicialización y día de referencia del TSB. Fuente: [pandas ewm](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.ewm.html).
6. FIT y streams generan `moving_time` contando filas. Las nuevas integraciones de energía o ventanas de potencia deben usar intervalos de tiempo comprobados, sin integrar huecos ni concatenar descansos como segundos contiguos. Los valores nominales de peso/FTP del dashboard deben identificarse como estimados, no alimentar silenciosamente el modelo.

## Definición propuesta: fmt_cov_v1

Unidad de análisis: un atleta y un día local. Clave `(athlete_id, date)`, nunca el nombre. Primera versión retrospectiva al cierre del día; un análisis previo al entrenamiento necesita otro contrato que use exclusivamente información disponible a esa hora.

Vector inicial fijo de cuatro variables: `log(hrv_rmssd)`, `resting_hr`, `sleep_hours`, `daily_load`. El sueño se asigna al día de despertar según el proveedor. No intercambiar RMSSD y SDNN ni unir dispositivos sin registrar cambios de método. La carga puede transformarse con `log1p` si la auditoría lo justifica; esa decisión cambiaría la versión del modelo.

Para cada fecha t, propuesta inicial configurable:

- Baseline: 60 días anteriores a la ventana de evaluación; al menos 30 observaciones válidas por variable. Son parámetros de ingeniería pendientes de validación, no umbrales fisiológicos.
- Evaluación: 28 días terminando en t. Incluir el día anterior para obtener el primer cambio diario. Baseline y evaluación no se solapan.
- Calcular media `mu_j` y desviación `s_j` solo con baseline. Mantenerlas fijas durante toda la evaluación: `z[d,j]=(x[d,j]-mu_j)/s_j`.
- Calcular `delta_z[d]=z[d]-z[d-1]` únicamente entre días consecutivos. No saltar huecos.
- Requerir al menos 20 vectores completos de cambios en esos 28 días. Si falta una variable o su escala es cero, emitir estado de datos insuficientes; no cambiar dimensiones silenciosamente.
- `F_t = cov(delta_z, rowvar=False, ddof=1)`. Usar los mismos días completos para toda la matriz; la eliminación por pares puede producir una matriz incoherente.
- Descomponer la matriz simétrica con `numpy.linalg.eigh`; ordenar autovalores de mayor a menor. Tolerar solo pequeños negativos de redondeo, y tratar negativos materiales como error.

Publicar `trace=sum(diag(F))`, `lambda1_share=lambda1/trace` y `effective_rank=exp(-sum(p_i*log(p_i)))`, donde `p_i=lambda_i/trace` y los términos con cero se omiten. Si la traza es cero, las dos últimas métricas son `null`, no divisiones por cero. Mostrar autovectores solo como contribuciones estadísticas; si hay autovalores casi iguales, sus direcciones son inestables.

Mantener visibles los niveles de HRV, sueño y carga junto a su variabilidad. No convertir la traza en un porcentaje de preparación ni usar semáforos clínicos. Comparar únicamente ventanas con igual versión y conjunto de variables; conservar las escalas de baseline para explicar cambios de referencia.

## Integración en el proyecto

Crear `src/daily_features.py` para unificar wellness/actividades y `src/fmt_metrics.py` para funciones puras de cálculo. Son archivos propuestos, todavía inexistentes.

Flujo: `IntervalsClient → tabla diaria validada → calcular_fmt_diario → wellness_load.fmt → HTML/PDF`.

Contrato propuesto de función: `calcular_fmt_diario(daily_df, as_of, config) -> dict`. Entrada con unidades, procedencia y cobertura. Salida con `model_version`, `as_of`, `features`, `baseline_start/end`, `window_start/end`, `valid_days`, `coverage`, `status`, `reasons`, `trace`, `eigenvalues`, `lambda1_share`, `effective_rank`, `loadings` y `history`. Guardar parámetros y escalas de normalización. Serializar faltantes como `null`, nunca NaN/Infinity.

Invocar después de recopilar y normalizar el historial, antes de adjuntarlo a cada ciclista. Revisar las dos ramas de `generar_dashboard_perfil_interactivo`: biometría sin GPS y perfil con telemetría. `generar_html_dashboard_interactivo` ya transporta `wellness_load`; añadir allí la tarjeta y después una sección en `generar_informe_etapa_pdf`.

Panel propuesto: serie de traza con cobertura; distribución de autovalores; matriz de covarianza con etiquetas; variables originales y fechas. Mostrar «Variabilidad conjunta (experimental)», «Dirección dominante» y «Datos insuficientes». Descarga incremental con caché por atleta/fecha; primera consulta de aproximadamente 90 días, ajustada a ventanas inclusivas. No hace falta descargar FIT para esta primera fase.

## Ampliación y validación

La versión diaria no resuelve por sí sola el ejemplo del artículo de dos sesiones distintas con igual TSS. Una segunda fase debe añadir duración, tiempo en zonas con umbrales vigentes, trabajo mecánico y distribución de esfuerzos. Calcular la retención de potencia tras trabajo acumulado requiere peso histórico, integración temporal válida y esfuerzos comparables; las curvas máximas existentes no contienen todo ese contexto.

Pruebas de aceptación para la futura implementación:

- Modificar datos posteriores a t no altera la salida en t.
- Cambiar unidades de una variable, con su conversión consistente, no altera el resultado normalizado.
- Verificar simetría, semidefinición positiva y equivalencia entre traza y suma de autovalores.
- Series constantes, huecos, duplicados, errores HTTP y falta de HRV producen estados explícitos.
- Una secuencia sintética con varias variables perfectamente correlacionadas produce una dirección dominante: demuestra por qué no debe etiquetarse como un único órgano afectado.
- Ambas ramas HTML y el PDF muestran la misma fecha, cobertura y valores; no filtran datos de otro atleta.

Evaluación posterior con históricos: particiones cronológicas y por atleta, sin usar datos futuros para normalizar; comparar con variables individuales y CTL/ATL/TSB sobre objetivos observables definidos de antemano, por ejemplo rendimiento en un esfuerzo estandarizado. Documentar error, cobertura y utilidad incremental. Evitar etiquetas de entrenamiento generadas a partir del propio FMT.

Posponer Transformer, fPCA intradiaria y explicación mediante LLM hasta contar con señales adecuadas, objetivos y evaluación fuera de muestra. Un LLM no sustituye el cálculo ni valida las interpretaciones fisiológicas del artículo. La primera fase puede ejecutarse localmente con NumPy y pandas.

## Alcance del estudio

Se revisaron los módulos citados, el flujo HTML/PDF y el artículo completo. Se contrastaron las definiciones de covarianza y decaimiento exponencial con documentación primaria. No se consultaron datos personales mediante la API, no se midió cobertura real, no se entrenaron modelos y no se modificó código de producción. El siguiente entregable sería la auditoría de cobertura y el prototipo numérico con las pruebas anteriores.
