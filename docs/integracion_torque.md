# Estudio de Integración del Torque en el Análisis de Archivos FIT

Fecha: 2026-09-13. Estado: Propuesta técnica y de arquitectura (estudio previo para intervals_fit_analytics).

---

## 1. Conclusión y Resumen Ejecutivo

La integración del análisis de **Torque (par de fuerza en bielas)** en el pipeline de telemetría `.fit` de `intervals_fit_analytics` es **100% viable**, altamente enriquecedora y **no requiere dependencias externas nuevas** (aprovecha NumPy, Pandas, Scipy y Matplotlib ya presentes en el entorno).

El análisis de potencia tradicional ($W$ y $W/\text{kg}$) mide el rendimiento metabólico y el gasto energético global, pero es **ciego a la estrategia neuromuscular y biomecánica** empleada por el ciclista. Dos atletas produciendo exactamente 450 W en un ataque pueden estar sufriendo un estrés fisiológico totalmente distinto:
- **Ciclista A (alta cadencia, 105 rpm)**: Produce un torque de **40.9 N·m**. El esfuerzo es predominantemente cardiovascular y de eficiencia aeróbica/oxidativa.
- **Ciclista B (baja cadencia, 68 rpm)**: Produce un torque de **63.2 N·m** (+54% de fuerza por pedalada). El esfuerzo exige un reclutamiento masivo de unidades motoras de contracción rápida (fibras Tipo IIx/IIa), acelerando la depleción de glucógeno y la fatiga neuromuscular periférica.

La arquitectura propuesta contempla un **enfoque dual**:
1. **Detección y extracción nativa**: Si el potenciómetro (Garmin Rally/Vector, Favero Assioma, Shimano R9100/9200-P, SRM, Quarq) grabó campos de torque, efectividad del par (`torque_effectiveness`) o suavidad de pedaleo (`pedal_smoothness`) en los mensajes `record` del FIT, se extraen directamente.
2. **Derivación física continua (1 Hz)**: En cualquier archivo FIT estándar con potencia y cadencia (comprobado en la telemetría del equipo en `data/today_race/`), el torque instantáneo se calcula matemáticamente segundo a segundo con filtros de estabilidad ($cad \ge 15\text{ rpm}$) y prevención de artefactos.

Las herramientas resultantes permitirán incorporar en el proyecto:
- **Análisis de Cuadrantes (Quadrant Analysis de Coggan & Allen)** interactivo en el dashboard web y en el informe PDF.
- **Curva de Picos de Torque Máximo (Mean Maximal Torque - MMT)**: 1s, 5s, 10s, 30s, 1m, 5m (evaluación de arrancada y fuerza explosiva).
- **Canal de Torque y Fuerza Efectiva (AEPF)** sincronizado en el perfil interactivo de etapa.
- **Degradación Neuromuscular por Fatiga**: pérdida de capacidad de torque tras 1500, 2500 y 3500 kJ de trabajo acumulado.

---

## 2. Fundamentos Físicos, Matemáticos y Biomecánicos

### 2.1. Relación Potencia - Torque - Velocidad Angular
En la cinemática del pedaleo rotacional, la potencia mecánica entregada a los platos de la bicicleta es el producto del torque neto ejercido en el eje de las bielas por la velocidad angular:

$$P = \tau \times \omega$$

Donde:
- $P$: Potencia mecánica en vatios ($\text{W}$ o $\text{J/s}$).
- $\tau$: Momento de torsión o torque en Newton-metro ($\text{N}\cdot\text{m}$).
- $\omega$: Velocidad angular del eje de pedalier en radianes por segundo ($\text{rad/s}$).

Dado que la cadencia de pedaleo ($cad$) se registra comúnmente en revoluciones por minuto ($\text{rpm}$):

$$\omega = cad \times \frac{2\pi}{60} \approx cad \times 0.104719755 \quad [\text{rad/s}]$$

Despejando el torque instantáneo $\tau$:

$$\tau = \frac{P}{\omega} = \frac{60 \times P}{2\pi \times cad} \approx 9.5492966 \times \frac{P}{cad} \quad [\text{N}\cdot\text{m}]$$

### 2.2. Fuerza Efectiva Media en el Pedal (AEPF - Average Effective Pedal Force)
El torque aplicado sobre la biela es el producto de la fuerza tangencial perpendicular a la biela por la longitud de dicha biela ($L_{\text{biela}}$):

$$\tau = \text{AEPF} \times L_{\text{biela}} \implies \text{AEPF} = \frac{\tau}{L_{\text{biela}}} \quad [\text{N}]$$

Para la longitud estándar del pelotón profesional ($L_{\text{biela}} = 172.5\text{ mm} = 0.1725\text{ m}$):

$$\text{AEPF} = \frac{\tau}{0.1725} \approx 5.7971 \times \tau \quad [\text{N}]$$

En términos de kilogramos-fuerza equivalentes (fuerza que el ciclista "apisona" en cada ciclo):

$$\text{kgf} = \frac{\text{AEPF}}{g} = \frac{\text{AEPF}}{9.80665} \approx 0.5911 \times \tau \quad [\text{kgf}]$$

*Ejemplo práctico comprobado en los datos del equipo*:
En un sprint de $755\text{ W}$ a $92\text{ rpm}$:
- $\tau = 78.35\text{ N}\cdot\text{m}$
- $\text{AEPF} = 454.2\text{ N} \approx 46.3\text{ kgf}$ de fuerza efectiva sostenida en cada pedalada.

### 2.3. Velocidad Circunferencial del Pedal (CPV - Circumferential Pedal Velocity)
Mide la velocidad lineal a la que se desplaza el pedal a lo largo de su circunferencia de 360°:

$$\text{CPV} = \omega \times L_{\text{biela}} = cad \times \frac{2\pi}{60} \times L_{\text{biela}} \quad [\text{m/s}]$$

A $90\text{ rpm}$ con biela de $172.5\text{ mm}$, $\text{CPV} = 1.626\text{ m/s}$.

### 2.4. Perfil Fuerza-Velocidad (F-v) y Potencia-Cadencia (P-cad)
Basado en el modelo clásico de Hill y las adaptaciones para ciclismo de Vandewalle, Dorel y Morin:
La fuerza/torque máximo disponible por un ciclista decae de forma cuasi-lineal respecto a la velocidad angular:

$$\tau_{\max}(cad) = T_0 \cdot \left(1 - \frac{cad}{cad_0}\right)$$

Donde:
- $T_0$: Torque máximo teórico a cadencia 0 (fuerza isométrica pura de arrancada en parado).
- $cad_0$: Cadencia máxima teórica con carga cero (límite neuromuscular de contracción rápida).
- Cadencia óptima de sprint: $cad_{\text{opt}} = \frac{cad_0}{2}$.
- Potencia máxima de sprint teórico: $P_{\max} = \frac{T_0 \times (cad_0 \cdot \frac{2\pi}{60})}{4}$.

Al computar la envolvente de picos de torque por tramos de cadencia (bins de 5 rpm) en la etapa, se puede trazar la recta de regresión que caracteriza el fenotipo del corredor: **Atleta de Torque/Fuerza** vs **Atleta de Velocidad/Cadencia**.

---

## 3. Disponibilidad en Archivos FIT y Protocolo ANT+

### 3.1. Auditoría de Archivos FIT del Repositorio
Se analizaron los archivos `.fit` de competición del equipo ubicados en `data/today_race/` (ej. `20117221663.fit`, `20132190989.fit`, etc.) con `fitdecode`:
- Mensajes presentes: `file_id`, `activity`, `session`, `lap`, `sport`, `user_profile`, `record`.
- Campos presentes en `record`:
  `timestamp`, `power`, `cadence`, `speed`, `enhanced_speed`, `altitude`, `enhanced_altitude`, `heart_rate`, `distance`, `position_lat`, `position_long`, `grade`, `temperature`.
- **Hallazgo clave**: Los ciclocomputadores comerciales graban `power` y `cadence` en el 100% de los ciclistas con potenciómetro. No grabaron el campo nativo `torque` ni dinámicas de pedaleo en estas unidades específicas. Por tanto, la **derivación matemática continua** es el mecanismo universal y necesario para garantizar la cobertura de toda la plantilla.

### 3.2. Especificación de Campos Nativos en Powermeters Avanzados
Cuando se utilicen potenciómetros duales o perfiles completos ANT+ Bicycle Power (Device Type 11), el lector debe inspeccionar y priorizar si existen:

| Campo FIT | Tipo / Unidades | Descripción |
|---|---|---|
| `torque` o `crank_torque` | $\text{N}\cdot\text{m}$ (escalado a 1/32 N·m) | Par instantáneo o acumulado reportado por la galga extensométrica |
| `left_torque_effectiveness` | % (0 a 100) | Eficiencia del par pierna izq.: $\frac{P_{\text{positiva}}}{P_{\text{positiva}} + |P_{\text{negativa}}|} \times 100$ |
| `right_torque_effectiveness` | % (0 a 100) | Eficiencia del par pierna der. |
| `left_pedal_smoothness` | % (0 a 100) | Suavidad pierna izq.: $\frac{\tau_{\text{medio}}}{\tau_{\text{pico}}} \times 100$ en los 360° |
| `right_pedal_smoothness` | % (0 a 100) | Suavidad pierna der. |
| `left_right_balance` | % (0 a 100) | Distribución de potencia entre piernas |

### 3.3. Tratamiento Numérico y Filtrado de Artefactos en Datos Derivados
Para calcular el torque continuo sin generar anomalías numéricas:
1. **Cadencia Cero (Rueda libre / Coasting)**:
   Si $cad = 0$, el ciclista no está aplicando par propulsor. Asignar $\tau = 0.0$ y $\text{AEPF} = 0.0$ directamente (evitar división por cero).
2. **Umbral de Bajas Cadencias Transitorias ($cad < 15\text{ rpm}$)**:
   Al enganchar los pedales o detenerse, pueden existir registros con potencia residual (filtrada por el powermeter) y cadencias de 3-8 rpm. Si se calcula $\frac{P}{cad \cdot 0.1047}$, resultarían torques ficticios de $>300\text{ N}\cdot\text{m}$.
   *Regla*: Para $cad < 15\text{ rpm}$, establecer $\tau = 0.0$.
3. **Filtro Fisiológico Superior (Clipping)**:
   El torque pico absoluto en arrancada de velocistas de clase mundial en pista no supera los $220 - 250\text{ N}\cdot\text{m}$.
   *Regla*: Truncar valores superiores a $250.0\text{ N}\cdot\text{m}$ para filtrar fallos puntuales de telemetría.

```python
# Algoritmo de cálculo seguro de torque y fuerza efectiva
def calcular_torque_seguro(potencia: np.ndarray, cadencia: np.ndarray, crank_length_m: float = 0.1725) -> Tuple[np.ndarray, np.ndarray]:
    p = np.asarray(potencia, dtype=float)
    c = np.asarray(cadencia, dtype=float)
    omega = c * (2.0 * np.pi / 60.0)
    
    with np.errstate(divide='ignore', invalid='ignore'):
        trq = np.where(c >= 15.0, p / omega, 0.0)
        trq = np.nan_to_num(trq, nan=0.0, posinf=0.0, neginf=0.0)
        trq = np.clip(trq, 0.0, 250.0)
        
    aepf = trq / crank_length_m
    return trq, aepf
```

---

## 4. Métricas y Análisis de Alto Rendimiento

### 4.1. Quadrant Analysis (Análisis de Cuadrantes de Coggan & Allen)
Es la metodología estándar de oro en fisiología del ciclismo para evaluar la demanda biomecánica de una carrera.

Plantea un gráfico de dispersión bidimensional:
- **Eje Horizontal (X)**: Cadencia de pedaleo ($\text{rpm}$) o Velocidad Circunferencial del Pedal ($\text{CPV}$ en $\text{m/s}$).
- **Eje Vertical (Y)**: Torque en las bielas ($\text{N}\cdot\text{m}$) o Fuerza Efectiva en el Pedal ($\text{AEPF}$ en $\text{N}$).

#### Umbrales de División de los Cuadrantes:
1. **Umbral de Cadencia ($cad_{\text{thresh}}$)**: Cadencia media del ciclista pedaleando activamente o valor de referencia de umbral (típicamente $85\text{ rpm}$ o $90\text{ rpm}$).
2. **Umbral de Torque ($\tau_{\text{thresh}}$)**: Torque equivalente al Functional Threshold Power ($\text{FTP}$) a dicha cadencia de umbral:
   $$\tau_{\text{thresh}} = \frac{\text{FTP}}{cad_{\text{thresh}} \times \frac{2\pi}{60}}$$
   *Ejemplo*: Para $\text{FTP} = 380\text{ W}$ y $cad_{\text{thresh}} = 85\text{ rpm} \implies \tau_{\text{thresh}} = 42.7\text{ N}\cdot\text{m}$.

```
                 Torque (N·m)
                      ^
                      |
        CUADRANTE II  |  CUADRANTE I
    (Baja Cad, Alto Trq)| (Alta Cad, Alto Trq)
     Subidas empinadas| Ataques, sprints,
     y grandes desarrollos | arrancadas, escapadas
                      |
    ------------------+-------------------> Cadencia (rpm)
     (Umbral Trq)     |
                      |
       CUADRANTE III  |  CUADRANTE IV
    (Baja Cad, Bajo Trq)| (Alta Cad, Bajo Trq)
     Recuperación,    | Rodar a rueda en el
     bajada, suave    | pelotón a alta velocidad
                      |
```

#### Interpretación Fisiológica y Táctica:
- **Cuadrante I (QI - Alta Cadencia, Alto Torque)**:
  - *Contexto*: Sprints masivos, aceleraciones al salir de curvas en circuitos/criteriums, ataques secos en el pelotón, persecuciones.
  - *Fisiología*: Máxima demanda glucolítica y neuromuscular; alta tasa de reclutamiento de fibras rápidas combinada con altísimo flujo sanguíneo y estrés cardíaco.
- **Cuadrante II (QII - Baja Cadencia, Alto Torque)**:
  - *Contexto*: Puertos con rampas duras (>8-12%), arrancadas desde parado o curvas cerradas en subida, pedalear atrancado con viento de cara.
  - *Fisiología*: Elevada tensión muscular intramuscular, oclusión vascular transitoria en el ciclo de pedalada, reclutamiento periférico forzado de fibras IIa/IIx. Gran predictor de sobrecarga patelar o fatiga muscular temprana.
- **Cuadrante III (QIII - Baja Cadencia, Bajo Torque)**:
  - *Contexto*: Tramos de bajada pedaleando para mantener inercia, zonas de transición neutralizadas, descolgado rodando cómodo.
  - *Fisiología*: Recuperación activa, aclaramiento de lactato, esfuerzo sub-aeróbico.
- **Cuadrante IV (QIV - Alta Cadencia, Bajo Torque)**:
  - *Contexto*: Rodar protegido en el pelotón llano a 50-60 km/h, alta cadencia con poca resistencia gracias al rebufo.
  - *Fisiología*: Esfuerzo aeróbico de alta eficiencia muscular, bajo estrés de tensión por pedalada, menor fatiga muscular periférica pero moderada demanda ventilatoria.

#### Curvas de Iso-Potencia:
Sobre el diagrama de cuadrantes se trazan curvas hiperbólicas de igual potencia ($P = \tau \times \omega = \text{constante}$):
$$\tau(cad) = \frac{P}{cad \times 0.1047}$$
Permiten ver visualmente cómo un mismo vatiaje (ej. 300W o el FTP) atraviesa los distintos cuadrantes.

---

### 4.2. Mean Maximal Torque (MMT) - Curva de Picos de Torque
De forma análoga a la curva de potencia máxima (MMP), se calcula el par medio máximo en ventanas móviles estándar:

| Ventana | Métrica | Significado Fisiológico y Táctico |
|---|---|---|
| **1 segundo** | $\tau_{1s}$ (Torque Pico) | Capacidad neuromuscular máxima instantánea (arrancada pura de parado o de sprint). |
| **5 segundos** | $\tau_{5s}$ | Fuerza explosiva de aceleración inicial para abrir hueco en un demarraje. |
| **10 segundos** | $\tau_{10s}$ | Capacidad de lanzamiento de sprint. |
| **30 segundos** | $\tau_{30s}$ | Capacidad de sprint largo o cierre de cortes en viento de costado. |
| **1 minuto** | $\tau_{1m}$ | Torque en repechos violentos de alta pendiente (muros flamencos / cotas). |
| **5 minutos** | $\tau_{5m}$ | Torque sostenido en subida a ritmo de $\text{VO}_2\max$. |
| **20 minutos** | $\tau_{20m}$ | Torque sostenible en el umbral funcional (FTP). |

*Prueba empírica con archivo real del equipo*:
- $1s$: **133.0 N·m** (Fuerza efectiva en pedal: $771.2\text{ N} \approx 78.6\text{ kgf}$)
- $5s$: **71.5 N·m**
- $30s$: **49.0 N·m**
- $5m$: **37.5 N·m**
- $20m$: **34.4 N·m**

---

### 4.3. Degradación de Torque por Fatiga Acumulada
Uno de los descubrimientos más valiosos del análisis de torque moderno en el WorldTour es el **desgaste neuromuscular tras gasto energético acumulado**:
- Evaluar el torque máximo y medio en los primeros 1000 kJ vs tras 2000 kJ y 3000 kJ.
- Un corredor puede tener un FTP de 400W en fresco, pero perder un 30% de su capacidad de torque pico ($1s-5s$) en la última hora de carrera. La correlación entre Trabajo Acumulado (kJ) y Capacidad de Torque es el indicador definitivo de resistencia a la fatiga (*durability / resilience*).

---

### 4.4. Zonas de Torque (Torque Zones)
Definir 6 zonas biomecánicas basadas en el Torque a FTP ($\tau_{\text{FTP}}$):

| Zona | Denominación | Rango (% $\tau_{\text{FTP}}$) | Descripción |
|---|---|---|---|
| **Z1** | Spin Ligero | $< 50\%$ | Rodar sin tensión en biela, calentamiento/enfriamiento |
| **Z2** | Fuerza Aeróbica Base | $50\% - 75\%$ | Resistencia aeróbica en llano a cadencia estable |
| **Z3** | Tensión Media / Tempo | $75\% - 95\%$ | Ritmo sostenido de carrera en grupo o falso llano |
| **Z4** | Umbral de Torque | $95\% - 115\%$ | Tensión correspondiente al ritmo umbral en puertos medios |
| **Z5** | Supra-Umbral / Fuerza Alta | $115\% - 150\%$ | Rampas duras, cambios de ritmo, cortes en el pelotón |
| **Z6** | Neuromuscular Máximo | $> 150\%$ | Esfuerzos anaeróbicos máximos, sprints, arrancadas |

---

## 5. Propuesta de Arquitectura e Integración en el Codebase

```
intervals_fit_analytics/
│
├── config.py                       <- DEFAULT_CRANK_LENGTH, umbrales de torque
│
├── src/
│   ├── fit_analyzer.py             <- Extracción nativa en cargar_fit + cálculo seguro de torque/aepf
│   │
│   ├── torque_analytics.py [NUEVO] <- Módulo puro de análisis biomecánico:
│   │                                  • calcular_metricas_torque()
│   │                                  • calcular_analisis_cuadrantes()
│   │                                  • calcular_picos_torque() (MMT)
│   │                                  • calcular_perfil_fuerza_velocidad()
│   │                                  • calcular_degradacion_torque_por_fatiga()
│   │
│   ├── interactive_profile.py      <- Inclusión en procesar_telemetria_ciclista:
│   │                                  • Interpolación espacial y temporal de trq/aepf
│   │                                  • Canal de Torque en gráfica interactiva sincronizada
│   │                                  • Componente visual de Quadrant Analysis (Chart.js / SVG)
│   │                                  • Ficha de métricas de pedaleo por ciclista
│   │
│   ├── pdf_reports.py              <- Sección de Torque y Cuadrantes en generar_informe_etapa_pdf:
│   │                                  • Scatter plot de Cuadrantes con isolíneas
│   │                                  • Tabla de Picos de Torque (1s, 5s, 30s) comparativa
│   │
│   └── cli.py                      <- Flag --torque o subcomando de inspección rápida
```

### 5.1. Módulo `src/fit_analyzer.py`
Modificar `cargar_fit`:
- Leer campos nativos si existen:
  ```python
  trq_native = campos.get('torque', campos.get('crank_torque'))
  te_left = campos.get('left_torque_effectiveness')
  te_right = campos.get('right_torque_effectiveness')
  ps_left = campos.get('left_pedal_smoothness')
  ps_right = campos.get('right_pedal_smoothness')
  ```
- Incorporar `torque` y `aepf` al DataFrame con derivación continua si no vienen nativos:
  ```python
  # Dentro de cargar_fit y cargar_fit_con_tiempo_movimiento:
  omega = df['cadencia'] * (2.0 * np.pi / 60.0)
  df['torque'] = np.where(df['cadencia'] >= 15.0, df['potencia'] / omega, 0.0)
  df['torque'] = np.nan_to_num(df['torque'], nan=0.0).clip(0.0, 250.0)
  df['aepf'] = df['torque'] / DEFAULT_CRANK_LENGTH
  ```

### 5.2. Nuevo Módulo `src/torque_analytics.py`
Funciones modulares puras sin acoplamiento a la interfaz:
```python
def calcular_metricas_torque(df: pd.DataFrame, ftp: float, crank_length_m: float = 0.1725, cad_thresh: float = 85.0) -> Dict[str, Any]:
    """Calcula el conjunto integral de métricas de torque, cuadrantes y picos."""
```
Salida estructurada:
- `torque_media_nm`, `torque_max_nm`, `torque_p95_nm`, `torque_mediana_nm`
- `aepf_media_n`, `aepf_max_n`, `aepf_p95_n`
- `mmt`: diccionario con picos `{1: val, 5: val, 10: val, 30: val, 60: val, 300: val, 1200: val}`
- `cuadrantes`: porcentajes y segundos en `{q1_pct, q2_pct, q3_pct, q4_pct, q1_sec, ...}`
- `zonas_torque`: segundos y porcentaje en cada una de las 6 zonas
- `fv_profile`: parámetros lineales `t0`, `cad0`, `pmax`, `cad_opt`, `r2`

### 5.3. Dashboard Interactivo (`src/interactive_profile.py`)
1. **Arrays de muestreo**:
   En `samples_by_dist` y `samples_by_time`, añadir las claves:
   - `'trq'`: Torque suavizado en $\text{N}\cdot\text{m}$.
   - `'aepf'`: Fuerza media efectiva en $\text{N}$.
2. **Canal de Telemetría**:
   En el selector de series del perfil de altimetría (donde se alternan Potencia, FC, Velocidad, CdA, Pendiente), añadir **Torque (N·m)**.
3. **Panel de Análisis de Cuadrantes**:
   Un nuevo widget visual interactivo en HTML/CSS/JS:
   - Muestra el scatter plot Cadencia vs Torque de los corredores seleccionados.
   - Pinta las 4 regiones (Q I, Q II, Q III, Q IV) con fondos semitransparentes sutiles.
   - Permite filtrar por tramos de la etapa (ej. últimos 20 km o un puerto específico).
   - Muestra las tarjetas resumen con el reparto del tiempo en cada cuadrante.

### 5.4. Informe PDF de Etapa (`src/pdf_reports.py`)
En `generar_informe_etapa_pdf`:
- Añadir en la página de rendimiento o como página dedicada:
  - Gráfico de dispersión Cuadrantes de Potencia/Torque con los colores distintivos de cada corredor.
  - Tabla comparativa de picos MMT: $\tau_{1s}$, $\tau_{5s}$, $\tau_{30s}$ y torque medio en subidas clave.

---

## 6. Plan de Fases de Implementación y Criterios de Aceptación

### Fase 1: Extracción en FIT y Módulo de Cálculo Puro
- Actualizar `config.py` con `DEFAULT_CRANK_LENGTH = 0.1725`.
- Actualizar `cargar_fit` y `cargar_fit_con_tiempo_movimiento` en `src/fit_analyzer.py` para extraer y derivar `torque` y `aepf`.
- Crear `src/torque_analytics.py` con cálculo de MMT, Cuadrantes, Zonas y F-v.
- Pruebas unitarias automatizadas con series sintéticas y archivos reales en `data/today_race/`.

### Fase 2: Integración en el Dashboard Interactivo
- Integrar en `procesar_telemetria_ciclista` de `src/interactive_profile.py`.
- Generar canales `'trq'` y `'aepf'` en las rejillas de distancia y tiempo.
- Renderizar en el template HTML la vista de Cuadrantes interactiva y el canal en el HUD.

### Fase 3: Integración en Informes PDF de Etapa y CLI
- Añadir sección de análisis de torque y cuadrantes en `generar_informe_etapa_pdf` en `src/pdf_reports.py`.
- Incorporar opción o comando en `cli.py` para generar reportes y visualizaciones de torque individuales o colectivas.

### Criterios de Validación:
1. **Consistencia matemática**: Para todo registro con $cad \ge 15\text{ rpm}$, $P \equiv \tau \times cad \times \frac{2\pi}{60}$ (margen de error $< 0.1\%$).
2. **Robustez ante paradas**: En coasting ($cad = 0$ o $P = 0$), $\tau = 0.0$ sin excepciones por división por cero ni NaNs en las salidas JSON/HTML.
3. **Invarianza temporal**: La suma de segundos en los 4 cuadrantes debe igualar exactamente al tiempo total en movimiento pedaleando.
4. **Validación visual**: Los gráficos de cuadrantes deben ubicar correctamente a escaladores en QII en pendientes duras y a sprinters en QI en aceleraciones.
