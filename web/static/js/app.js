/**
 * Intervals Fit Analytics - SPA Frontend Application Controller
 * Gestión de pestañas, peticiones REST, gráficos Chart.js y componentes dinámicos
 */

// Estado global de la aplicación
const AppState = {
  athletes: [],
  currentTab: 'tab-dashboard',
  racesCalendar: [],
  raceFilter: 'all',
  peaksChart: null,
  mmpChart: null,
  raceHistoryChart: null,
  cachedRaceHistoryStages: [],
  cachedRaceHistorySummary: [],
  isSyncing: false
};

// =============================================================================
// UTILIDADES & NOTIFICACIONES TOAST
// =============================================================================

function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  const icon = type === 'success' ? '✅' : (type === 'error' ? '❌' : 'ℹ️');
  toast.innerHTML = `<span>${icon}</span><span>${message}</span>`;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// =============================================================================
// GESTIÓN DE TEMA (CLARO / OSCURO)
// =============================================================================

function initTheme() {
  const savedTheme = localStorage.getItem('intervals_theme') || 'light';
  applyTheme(savedTheme);

  document.getElementById('btn-theme-toggle')?.addEventListener('click', () => {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';
    applyTheme(newTheme);
    localStorage.setItem('intervals_theme', newTheme);
  });
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const icon = document.getElementById('theme-toggle-icon');
  const text = document.getElementById('theme-toggle-text');
  if (icon && text) {
    if (theme === 'light') {
      icon.textContent = '🌙';
      text.textContent = 'Modo Oscuro';
    } else {
      icon.textContent = '☀️';
      text.textContent = 'Modo Claro';
    }
  }

  updateChartsTheme();
}

function getChartTextColor() {
  return (document.documentElement.getAttribute('data-theme') === 'dark') ? '#94a3b8' : '#475569';
}

function getChartGridColor() {
  return (document.documentElement.getAttribute('data-theme') === 'dark') ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.06)';
}

function updateChartsTheme() {
  const textColor = getChartTextColor();
  const gridColor = getChartGridColor();

  [AppState.peaksChart, AppState.mmpChart, AppState.raceHistoryChart].forEach(chart => {
    if (!chart) return;
    if (chart.options.scales) {
      Object.values(chart.options.scales).forEach(scale => {
        if (scale.ticks) scale.ticks.color = textColor;
        if (scale.grid) scale.grid.color = gridColor;
        if (scale.title) scale.title.color = textColor;
      });
    }
    if (chart.options.plugins?.legend?.labels) {
      chart.options.plugins.legend.labels.color = textColor;
    }
    chart.update();
  });
}

function navigateToTab(tabId) {
  document.querySelectorAll('.nav-item').forEach(item => {
    if (item.getAttribute('data-tab') === tabId) {
      item.classList.add('active');
    } else {
      item.classList.remove('active');
    }
  });

  document.querySelectorAll('.tab-view').forEach(view => {
    if (view.id === tabId) {
      view.classList.add('active');
    } else {
      view.classList.remove('active');
    }
  });

  AppState.currentTab = tabId;

  // Actualizar título de la página
  const titles = {
    'tab-dashboard': 'Dashboard General del Equipo',
    'tab-stage': 'Análisis de Etapa y Perfil Interactivo',
    'tab-reports': 'Informes de Rendimiento y Potencias',
    'tab-records': 'Mejores Números y Fatiga Previa (kJ)',
    'tab-admin': 'Gestión de Ciclistas y Carreras'
  };
  document.getElementById('page-title').textContent = titles[tabId] || 'Intervals Fit Analytics';

  // Cargar datos específicos de la pestaña
  if (tabId === 'tab-dashboard') loadDashboardData();
  if (tabId === 'tab-stage') loadStageProfilesList();
  if (tabId === 'tab-reports') loadPowerReport();
  if (tabId === 'tab-records') loadRecordsView();
  if (tabId === 'tab-admin') {
    loadAthletesAdmin();
    loadRacesAdmin();
  }
}

// =============================================================================
// MÓDULO 1: DASHBOARD GENERAL
// =============================================================================

function getCountryFlag(pais) {
  const flagMap = {
    'españa': '🇪🇸', 'spain': '🇪🇸',
    'portugal': '🇵🇹',
    'francia': '🇫🇷', 'france': '🇫🇷',
    'italia': '🇮🇹', 'italy': '🇮🇹',
    'eslovenia': '🇸🇮', 'slovenia': '🇸🇮',
    'bélgica': '🇧🇪', 'belgium': '🇧🇪',
    'ruanda': '🇷🇼', 'rwanda': '🇷🇼',
    'china': '🇨🇳',
    'albania': '🇦🇱',
    'benin': '🇧🇯',
    'méxico': '🇲🇽', 'mexico': '🇲🇽',
    'colombia': '🇨🇴',
    'alemania': '🇩🇪', 'germany': '🇩🇪',
    'reino unido': '🇬🇧', 'uk': '🇬🇧',
    'países bajos': '🇳🇱', 'netherlands': '🇳🇱',
    'suiza': '🇨🇭', 'switzerland': '🇨🇭',
    'noruega': '🇳🇴', 'norway': '🇳🇴',
    'dinamarca': '🇩🇰', 'denmark': '🇩🇰'
  };
  const p = (pais || '').trim().toLowerCase();
  return flagMap[p] || '🏁';
}

function escapeJs(str) {
  if (!str) return '';
  return String(str).replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

async function loadDashboardData() {
  try {
    const res = await fetch('/api/dashboard');
    if (!res.ok) throw new Error('Error al cargar dashboard');
    const data = await res.json();

    AppState.athletes = data.ciclistas || [];

    // Actualizar KPIs
    document.getElementById('kpi-total-athletes').textContent = data.total_ciclistas;
    const activeCount = (data.carreras_activas && data.carreras_activas.length > 0)
      ? data.carreras_activas.reduce((acc, c) => acc + (c.num_convocados || (c.convocados ? c.convocados.length : 0)), 0)
      : ((data.en_carrera_1?.length || 0) + (data.en_carrera_2?.length || 0));
    document.getElementById('kpi-active-racers').textContent = `${activeCount} activos en carrera`;

    document.getElementById('kpi-total-activities').textContent = data.db_stats?.num_actividades || 0;
    const racesCount = data.total_carreras ?? data.db_stats?.num_carreras ?? 0;
    document.getElementById('kpi-races-count').textContent = `${racesCount} carreras registradas`;

    const totalKj = data.db_stats?.total_kj_registrados || 0;
    document.getElementById('kpi-total-work').textContent = `${(totalKj).toLocaleString()} kJ`;

    document.getElementById('kpi-total-peaks').textContent = data.db_stats?.num_picos_registrados || 0;

    const dbSize = data.db_stats?.tamano_kb || 0;
    document.getElementById('sidebar-db-size').textContent = `${dbSize} KB`;

    // Renderizar Bloques de Carreras en Vivo o Próximas en Dashboard
    renderDashboardRaces(data.carreras_activas, data.proxima_carrera, data.ultima_carrera, data.grupos);

    // Cargar carreras para selectores de informe de potencia
    loadRacesForSelects(data.grupos);

    // Últimas etapas registradas
    const tbodyStages = document.getElementById('tbody-recent-stages');
    if (data.ultimas_etapas && data.ultimas_etapas.length > 0) {
      tbodyStages.innerHTML = data.ultimas_etapas.map(et => `
        <tr>
          <td><strong>${et.nombre_carrera || et.carrera_id}</strong></td>
          <td><span class="badge badge-race-1">Etapa ${et.etapa_num}</span></td>
          <td class="mono">${et.fecha}</td>
          <td>${et.num_ciclistas} ciclistas</td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="viewStageDate('${et.fecha}')">
              <span>🗺️</span> Ver Perfil
            </button>
          </td>
        </tr>
      `).join('');
    } else {
      tbodyStages.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-dim);">No hay etapas registradas aún.</td></tr>`;
    }

  } catch (err) {
    console.error(err);
    showToast('Error al conectar con el servidor', 'error');
  }
}

function renderRosterList(elementId, athletes, badgeId, label) {
  const ul = document.getElementById(elementId);
  const badge = document.getElementById(badgeId);
  if (!ul) return;

  if (!athletes || athletes.length === 0) {
    ul.innerHTML = `<li style="color: var(--text-dim);">Sin ciclistas asignados.</li>`;
    if (badge) badge.textContent = `0 corredores`;
    return;
  }

  if (badge) badge.textContent = `${athletes.length} corredores`;
  ul.innerHTML = athletes.map(a => `
    <li style="display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--border-subtle);">
      <span><strong>${a.name}</strong> (${a.weight} kg, ${a.ftp} W)</span>
      <span class="mono" style="font-size: 0.8rem; color: var(--accent-cyan);">${a.intervals_id}</span>
    </li>
  `).join('');
}

function renderDashboardRaces(carrerasActivas, proximaCarrera, ultimaCarrera, fallbackGrupos) {
  const container = document.getElementById('race-groups-container');
  if (!container) return;

  // 1. Si hay carreras activas hoy en curso: mostrarlas
  if (carrerasActivas && carrerasActivas.length > 0) {
    container.innerHTML = carrerasActivas.map((c, idx) => {
      const flag = getCountryFlag(c.pais);
      const fechaStr = (c.fecha_inicio && c.fecha_fin) ? `${c.fecha_inicio} al ${c.fecha_fin}` : (c.fecha_inicio || '');
      const totalKm = c.dist_total_km || 0;
      const totalKj = c.kj_totales || 0;
      const progresoPct = c.progreso_pct ?? Math.min(100, Math.round(((c.etapa_actual || 0) / Math.max(c.total_etapas || 1, 1)) * 100));
      const cardColorClass = (idx % 2 === 0) ? 'race-card-c1' : 'race-card-c2';
      const fillClass = (idx % 2 === 0) ? 'fill-c1' : 'fill-c2';

      const convocados = c.convocados || [];
      const convocadosListHtml = convocados.length > 0
        ? convocados.map(a => `
            <li class="race-roster-item">
              <div>
                <strong>${a.name || a.atleta_id}</strong>
                <span style="font-size: 0.8rem; color: var(--text-dim);">(${a.weight || 70} kg, ${a.ftp || 380} W)</span>
              </div>
              <span class="mono" style="font-size: 0.8rem; color: var(--text-muted);">${a.atleta_id}</span>
            </li>
          `).join('')
        : `<li style="color: var(--text-dim); padding: 8px 0;">Sin ciclistas convocados a esta carrera.</li>`;

      return `
        <div class="race-card ${cardColorClass}">
          <div class="race-card-header">
            <div class="race-title-group">
              <div class="race-name">
                <span>${flag}</span>
                <span>${c.nombre_carrera}</span>
              </div>
              <div class="race-meta-sub">
                <span class="badge-uci">${c.categoria || 'UCI 2.Pro'}</span>
                <span>•</span>
                <span>${c.pais || 'España'}</span>
                <span>•</span>
                <span>${fechaStr}</span>
              </div>
            </div>
            <span class="badge-status badge-status-live">🟢 En Competición</span>
          </div>

          <div class="race-progress-box">
            <div class="race-progress-header">
              <span><strong>Etapa ${c.etapa_actual || 1}</strong> de ${c.total_etapas || 5}</span>
              <span>${progresoPct}% completado</span>
            </div>
            <div class="stage-progress-bar">
              <div class="stage-progress-fill ${fillClass}" style="width: ${progresoPct}%;"></div>
            </div>
          </div>

          <div class="race-mini-kpis">
            <div class="mini-kpi-item">
              <div class="mini-kpi-val" style="color: var(--accent-cyan);">${Math.round(totalKj).toLocaleString()} kJ</div>
              <div class="mini-kpi-lbl">⚡ Gasto Bloque</div>
            </div>
            <div class="mini-kpi-item">
              <div class="mini-kpi-val">${Math.round(totalKm).toLocaleString()} km</div>
              <div class="mini-kpi-lbl">📏 Dist. Acumulada</div>
            </div>
            <div class="mini-kpi-item">
              <div class="mini-kpi-val" style="color: var(--accent-emerald);">${convocados.length}</div>
              <div class="mini-kpi-lbl">👥 Convocados</div>
            </div>
          </div>

          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <span style="font-size: 0.82rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">
                Ciclistas Convocados (${convocados.length})
              </span>
              <button class="btn btn-secondary btn-sm" style="padding: 2px 8px; font-size: 0.75rem;" onclick="openConvocatoriaModal('${c.carrera_id}')">
                👥 Modificar
              </button>
            </div>
            <ul class="race-roster-list">
              ${convocadosListHtml}
            </ul>
          </div>

          <div class="race-card-actions">
            <button class="btn btn-primary btn-sm" onclick="openRaceHistoryModal('${c.carrera_id}', '${escapeJs(c.nombre_carrera)}')">
              <span>📊</span> Histórico de la Vuelta
            </button>
            <button class="btn btn-secondary btn-sm" onclick="openEditRaceModal('${c.carrera_id}')">
              <span>✏️</span> Editar Carrera
            </button>
          </div>
        </div>
      `;
    }).join('');
    return;
  }

  // 2. Si no hay carreras activas hoy, mostrar Teaser de Próxima Competición y/o Última Finalizada
  let cardsHtml = '';

  if (proximaCarrera) {
    const flag = getCountryFlag(proximaCarrera.pais);
    const fechaStr = (proximaCarrera.fecha_inicio && proximaCarrera.fecha_fin)
      ? `${proximaCarrera.fecha_inicio} al ${proximaCarrera.fecha_fin}`
      : proximaCarrera.fecha_inicio;
    const convocados = proximaCarrera.convocados || [];
    const convocadosTags = convocados.length > 0
      ? convocados.map(a => `<span class="convocado-tag">${a.name || a.atleta_id}</span>`).join('')
      : '<span style="color: var(--text-dim); font-size: 0.82rem;">Pendiente de asignar convocatoria</span>';

    cardsHtml += `
      <div class="race-card teaser-race-card">
        <div class="race-card-header">
          <div class="race-title-group">
            <div class="race-name">
              <span>${flag}</span>
              <span>${proximaCarrera.nombre_carrera}</span>
            </div>
            <div class="race-meta-sub">
              <span class="badge-uci">${proximaCarrera.categoria || 'UCI 2.Pro'}</span>
              <span>•</span>
              <span>${proximaCarrera.pais || 'España'}</span>
              <span>•</span>
              <span>${fechaStr}</span>
            </div>
          </div>
          <span class="badge-status badge-status-upcoming">📅 Próxima Competición</span>
        </div>

        <div style="background: var(--card-item-bg); border-radius: var(--radius-md); padding: 14px; margin-bottom: 16px; border: 1px solid var(--border-subtle);">
          <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 6px;">
            🏁 <strong>${proximaCarrera.total_etapas || 5} etapas</strong> programadas.
            ${proximaCarrera.notas ? `<span style="display: block; margin-top: 4px; color: var(--text-dim);">"${proximaCarrera.notas}"</span>` : ''}
          </div>
          <div style="margin-top: 10px;">
            <div style="font-size: 0.8rem; font-weight: 600; color: var(--text-muted); margin-bottom: 6px;">
              Ciclistas Convocados (${convocados.length}):
            </div>
            <div class="convocados-tag-list">
              ${convocadosTags}
            </div>
          </div>
        </div>

        <div class="race-card-actions">
          <button class="btn btn-primary btn-sm" onclick="openConvocatoriaModal('${proximaCarrera.carrera_id}')">
            <span>👥</span> Gestionar Convocatoria
          </button>
          <button class="btn btn-secondary btn-sm" onclick="openEditRaceModal('${proximaCarrera.carrera_id}')">
            <span>✏️</span> Editar Carrera
          </button>
        </div>
      </div>
    `;
  }

  if (ultimaCarrera) {
    const flag = getCountryFlag(ultimaCarrera.pais);
    const fechaStr = (ultimaCarrera.fecha_inicio && ultimaCarrera.fecha_fin)
      ? `${ultimaCarrera.fecha_inicio} al ${ultimaCarrera.fecha_fin}`
      : ultimaCarrera.fecha_fin;
    const totalKm = ultimaCarrera.dist_total_km || 0;
    const totalKj = ultimaCarrera.kj_totales || 0;
    const convocados = ultimaCarrera.convocados || [];

    cardsHtml += `
      <div class="race-card" style="border-left: 4px solid var(--text-muted);">
        <div class="race-card-header">
          <div class="race-title-group">
            <div class="race-name">
              <span>${flag}</span>
              <span>${ultimaCarrera.nombre_carrera}</span>
            </div>
            <div class="race-meta-sub">
              <span class="badge-uci">${ultimaCarrera.categoria || 'UCI 2.Pro'}</span>
              <span>•</span>
              <span>${ultimaCarrera.pais || 'España'}</span>
              <span>•</span>
              <span>${fechaStr}</span>
            </div>
          </div>
          <span class="badge-status badge-status-finished">🏁 Última Finalizada</span>
        </div>

        <div class="race-mini-kpis">
          <div class="mini-kpi-item">
            <div class="mini-kpi-val" style="color: var(--accent-cyan);">${Math.round(totalKj).toLocaleString()} kJ</div>
            <div class="mini-kpi-lbl">⚡ Gasto Total</div>
          </div>
          <div class="mini-kpi-item">
            <div class="mini-kpi-val">${Math.round(totalKm).toLocaleString()} km</div>
            <div class="mini-kpi-lbl">📏 Dist. Cubierta</div>
          </div>
          <div class="mini-kpi-item">
            <div class="mini-kpi-val">${convocados.length}</div>
            <div class="mini-kpi-lbl">👥 Participantes</div>
          </div>
        </div>

        <div class="race-card-actions">
          <button class="btn btn-primary btn-sm" onclick="openRaceHistoryModal('${ultimaCarrera.carrera_id}', '${escapeJs(ultimaCarrera.nombre_carrera)}')">
            <span>📊</span> Ver Balance Histórico
          </button>
          <button class="btn btn-secondary btn-sm" onclick="openEditRaceModal('${ultimaCarrera.carrera_id}')">
            <span>✏️</span> Editar
          </button>
        </div>
      </div>
    `;
  }

  if (!cardsHtml) {
    // Si no hay carreras activas ni próxima ni última, fallback a grupos tradicionales
    if (fallbackGrupos && (fallbackGrupos['1'] || fallbackGrupos['2'])) {
      renderRaceGroups(fallbackGrupos);
      return;
    }

    container.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; color: var(--text-dim); padding: 36px 20px; background: var(--card-item-bg); border-radius: var(--radius-lg); border: 1px dashed var(--border-subtle);">
        <div style="font-size: 2.5rem; margin-bottom: 10px;">🏆</div>
        <h4 style="color: var(--text-main); margin-bottom: 8px;">No hay competiciones registradas en el calendario</h4>
        <p style="font-size: 0.88rem; color: var(--text-muted); max-width: 500px; margin: 0 auto 16px auto;">
          Da de alta las carreras de la temporada con sus fechas de inicio, fin y ciclistas convocados para habilitar el seguimiento automático en vivo.
        </p>
        <button class="btn btn-primary" onclick="openCreateRaceModal()">
          <span>➕</span> Dar de Alta Primera Carrera
        </button>
      </div>
    `;
    return;
  }

  container.innerHTML = cardsHtml;
}

function renderRaceGroups(grupos) {
  const container = document.getElementById('race-groups-container');
  if (!container) return;

  const g1 = grupos['1'] || {};
  const g2 = grupos['2'] || {};

  const renderCard = (g, groupNum) => {
    const flag = getCountryFlag(g.pais);
    let statusBadgeClass = 'badge-status-upcoming';
    if (g.estado === 'en_curso') statusBadgeClass = 'badge-status-live';
    if (g.estado === 'finalizada') statusBadgeClass = 'badge-status-finished';

    const athletes = g.atletas || [];
    const athletesListHtml = athletes.length > 0
      ? athletes.map(a => {
          const lastStageInfo = a.ultima_etapa_km ? ` · <span style="color: var(--accent-cyan); font-size: 0.78rem;">Últ: ${a.ultima_etapa_km} km (${(a.ultima_etapa_kj || 0).toLocaleString()} kJ)</span>` : '';
          return `
            <li class="race-roster-item">
              <div>
                <strong>${a.name}</strong>
                <span style="font-size: 0.8rem; color: var(--text-dim);">(${a.weight} kg, ${a.ftp} W)</span>
                ${lastStageInfo}
              </div>
              <span class="mono" style="font-size: 0.8rem; color: var(--text-muted);">${a.intervals_id}</span>
            </li>
          `;
        }).join('')
      : `<li style="color: var(--text-dim); padding: 8px 0;">Sin ciclistas asignados a este grupo.</li>`;

    const fechaStr = (g.fecha_inicio && g.fecha_fin) ? `${g.fecha_inicio} a ${g.fecha_fin}` : (g.fecha_inicio || 'Fechas de carrera');
    const totalKm = g.stats?.dist_total_km || 0;
    const totalKj = g.stats?.kj_totales || 0;
    const tsbMedio = g.stats?.tsb_medio ?? 0;

    return `
      <div class="race-card race-card-c${groupNum}">
        <div class="race-card-header">
          <div class="race-title-group">
            <div class="race-name">
              <span>${flag}</span>
              <span>${g.nombre_carrera || `Grupo Carrera ${groupNum}`}</span>
            </div>
            <div class="race-meta-sub">
              <span class="badge-uci">${g.categoria || 'UCI 2.Pro'}</span>
              <span>•</span>
              <span>${g.pais || 'España'}</span>
              <span>•</span>
              <span>${fechaStr}</span>
            </div>
          </div>
          <span class="badge-status ${statusBadgeClass}">${g.estado_label || 'En Curso'}</span>
        </div>

        <div class="race-progress-box">
          <div class="race-progress-header">
            <span><strong>Etapa ${g.etapa_actual}</strong> de ${g.total_etapas}</span>
            <span>${g.progreso_pct}% completado</span>
          </div>
          <div class="stage-progress-bar">
            <div class="stage-progress-fill fill-c${groupNum}" style="width: ${g.progreso_pct}%;"></div>
          </div>
        </div>

        <div class="race-mini-kpis">
          <div class="mini-kpi-item">
            <div class="mini-kpi-val" style="color: var(--accent-cyan);">${(totalKj).toLocaleString()} kJ</div>
            <div class="mini-kpi-lbl">⚡ Gasto Bloque</div>
          </div>
          <div class="mini-kpi-item">
            <div class="mini-kpi-val">${totalKm.toLocaleString()} km</div>
            <div class="mini-kpi-lbl">📏 Dist. Acumulada</div>
          </div>
          <div class="mini-kpi-item">
            <div class="mini-kpi-val" style="color: ${tsbMedio >= 0 ? 'var(--accent-emerald)' : 'var(--accent-amber)'};">${tsbMedio > 0 ? '+' : ''}${tsbMedio}</div>
            <div class="mini-kpi-lbl">🔋 TSB Medio</div>
          </div>
        </div>

        <div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 0.82rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">
              Corredores Convocados (${athletes.length})
            </span>
          </div>
          <ul class="race-roster-list">
            ${athletesListHtml}
          </ul>
        </div>

        <div class="race-card-actions">
          <button class="btn btn-primary btn-sm" onclick="openRaceHistoryModal('${g.carrera_id_link || g.nombre_carrera}', '${escapeJs(g.nombre_carrera)}')">
            <span>📊</span> Histórico de la Vuelta
          </button>
          <button class="btn btn-secondary btn-sm" onclick="openGroupStageProfile('${g.stats?.ultima_fecha || ''}')">
            <span>🗺️</span> Ver Perfil Etapa
          </button>
          <button class="btn btn-secondary btn-sm" onclick="openRaceGroupConfigModal(${groupNum})">
            <span>✏️</span> Configurar Carrera
          </button>
        </div>
      </div>
    `;
  };

  container.innerHTML = renderCard(g1, 1) + renderCard(g2, 2);
}

function updateReportRaceSelect(races, grupos) {
  const sel = document.getElementById('report-select-group');
  if (!sel) return;

  const currentVal = sel.value;
  let html = `<option value="">Todo el Equipo (General)</option>`;

  if (races && races.length > 0) {
    html += `<optgroup label="🏆 Competiciones del Calendario">`;
    races.forEach(r => {
      const count = r.num_convocados ?? (r.convocados ? r.convocados.length : (r.num_atletas ?? 0));
      html += `<option value="race:${r.carrera_id}">${r.nombre_carrera} (${count} convocados)</option>`;
    });
    html += `</optgroup>`;
  }

  if (grupos) {
    html += `<optgroup label="Grupos Tradicionales">`;
    const g1Name = grupos['1']?.nombre_carrera || 'Grupo Carrera 1';
    const g2Name = grupos['2']?.nombre_carrera || 'Grupo Carrera 2';
    const g1Count = grupos['1']?.atletas?.length || 0;
    const g2Count = grupos['2']?.atletas?.length || 0;
    html += `
      <option value="1">Grupo 1: ${g1Name} (${g1Count} ciclistas)</option>
      <option value="2">Grupo 2: ${g2Name} (${g2Count} ciclistas)</option>
    `;
    html += `</optgroup>`;
  }

  sel.innerHTML = html;
  if (currentVal) sel.value = currentVal;
}

function updateStageRaceSelect(races, grupos) {
  const sel = document.getElementById('stage-select-group');
  if (!sel) return;

  const currentVal = sel.value;
  let html = `<option value="">-- Autodetectar carrera activa por fecha --</option>`;

  if (races && races.length > 0) {
    html += `<optgroup label="🏆 Competiciones del Calendario">`;
    races.forEach(r => {
      const count = r.num_convocados ?? (r.convocados ? r.convocados.length : (r.num_atletas ?? 0));
      html += `<option value="race:${r.carrera_id}">${r.nombre_carrera} (${count} convocados)</option>`;
    });
    html += `</optgroup>`;
  }

  if (grupos) {
    html += `<optgroup label="Grupos Tradicionales">`;
    const g1Name = grupos['1']?.nombre_carrera || 'Grupo Carrera 1';
    const g2Name = grupos['2']?.nombre_carrera || 'Grupo Carrera 2';
    const g1Count = grupos['1']?.atletas?.length || 0;
    const g2Count = grupos['2']?.atletas?.length || 0;
    html += `
      <option value="1">Grupo 1: ${g1Name} (${g1Count} ciclistas)</option>
      <option value="2">Grupo 2: ${g2Name} (${g2Count} ciclistas)</option>
    `;
    html += `</optgroup>`;
  }

  html += `<option value="todos">Todos los corredores (Sin filtro)</option>`;

  sel.innerHTML = html;
  if (currentVal) sel.value = currentVal;
}

async function loadRacesForSelects(grupos) {
  try {
    const res = await fetch('/api/races');
    if (res.ok) {
      AppState.racesCalendar = await res.json();
    }
  } catch (e) {
    // Silencioso
  }
  updateReportRaceSelect(AppState.racesCalendar, grupos);
  updateStageRaceSelect(AppState.racesCalendar, grupos);
}

function openGroupStageProfile(fecha) {
  if (!fecha) {
    showToast('No hay fecha de etapa registrada para este grupo', 'info');
    return;
  }
  viewStageDate(fecha);
}

function viewStageDate(fecha) {
  navigateToTab('tab-stage');
  const inputDate = document.getElementById('stage-input-date');
  if (inputDate) inputDate.value = fecha;
  document.getElementById('btn-run-stage-analysis')?.click();
}

// Sincronización en segundo plano con Intervals.icu
document.getElementById('btn-sync-api')?.addEventListener('click', async () => {
  if (AppState.isSyncing) {
    showToast('Ya hay una sincronización en curso', 'info');
    return;
  }
  try {
    AppState.isSyncing = true;
    document.getElementById('api-status-text').textContent = 'Sincronizando con Intervals...';
    showToast('Iniciando sincronización masiva...', 'info');

    const res = await fetch('/api/sync?desde=2026-01-01', { method: 'POST' });
    const data = await res.json();
    showToast(data.message, 'info');

    // Poll status cada 3 segundos
    const pollInterval = setInterval(async () => {
      const sRes = await fetch('/api/sync/status');
      const sData = await sRes.json();
      if (!sData.running) {
        clearInterval(pollInterval);
        AppState.isSyncing = false;
        document.getElementById('api-status-text').textContent = 'Conectado a Intervals.icu';
        showToast(sData.message, 'success');
        loadDashboardData();
      }
    }, 3000);
  } catch (err) {
    AppState.isSyncing = false;
    showToast('Error al solicitar sincronización', 'error');
  }
});

// =============================================================================
// MÓDULO 2: ANÁLISIS DE ETAPA Y PERFIL INTERACTIVO
// =============================================================================

async function loadStageProfilesList() {
  try {
    const res = await fetch('/api/stage/list');
    if (!res.ok) return;
    const data = await res.json();

    const select = document.getElementById('select-cached-profiles');
    if (!select) return;

    select.innerHTML = `<option value="">-- Seleccionar perfil generado recientemente --</option>`;
    if (data.html_profiles && data.html_profiles.length > 0) {
      data.html_profiles.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.view_url;
        opt.textContent = `${p.title} (${p.created_at})`;
        select.appendChild(opt);
      });
    }
  } catch (err) {
    console.error(err);
  }
}

document.getElementById('select-cached-profiles')?.addEventListener('change', (e) => {
  const url = e.target.value;
  if (!url) return;
  const box = document.getElementById('stage-viewer-box');
  box.innerHTML = `<iframe src="${url}" title="Perfil Interactivo"></iframe>`;
});

document.getElementById('btn-run-stage-analysis')?.addEventListener('click', async () => {
  const btn = document.getElementById('btn-run-stage-analysis');
  const fecha = document.getElementById('stage-input-date').value;
  const grupoVal = document.getElementById('stage-select-group').value;
  const titulo = document.getElementById('stage-input-title').value;

  btn.disabled = true;
  btn.innerHTML = `<span>⏳</span><span>Procesando Etapa...</span>`;
  showToast(`Procesando datos de la etapa para el ${fecha}...`, 'info');

  const box = document.getElementById('stage-viewer-box');
  box.innerHTML = `
    <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--accent-cyan); gap: 16px;">
      <div style="font-size: 3rem; animation: pulse-dot 1.5s infinite;">🚴‍♂️</div>
      <p style="font-weight: 600;">Descargando y sincronizando telemetría FIT de los ciclistas...</p>
      <p style="font-size: 0.85rem; color: var(--text-dim);">Esto puede tardar entre 10 y 25 segundos.</p>
    </div>
  `;

  try {
    const payload = {
      fecha: fecha,
      titulo: titulo || undefined,
      generar_pdf: true,
      generar_docx: true
    };
    if (grupoVal === 'todos') {
      payload.todos = true;
    } else if (grupoVal && grupoVal.startsWith('race:')) {
      payload.carrera_id = grupoVal.replace('race:', '');
    } else if (grupoVal) {
      payload.grupo_carrera = parseInt(grupoVal);
    }

    const res = await fetch('/api/stage/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.detail || 'Error al analizar etapa');
    }

    const data = await res.json();
    showToast(data.mensaje || '¡Perfil generado con éxito!', 'success');

    // Cargar iframe
    if (data.archivos?.html) {
      box.innerHTML = `<iframe src="${data.archivos.html}" title="Perfil Interactivo"></iframe>`;
    }

    // Mostrar botones de descarga
    const btnPdf = document.getElementById('btn-download-stage-pdf');
    const btnDocx = document.getElementById('btn-download-stage-docx');

    if (data.archivos?.pdf) {
      btnPdf.href = data.archivos.pdf;
      btnPdf.style.display = 'inline-flex';
    } else {
      btnPdf.style.display = 'none';
    }

    if (data.archivos?.docx) {
      btnDocx.href = data.archivos.docx;
      btnDocx.style.display = 'inline-flex';
    } else {
      btnDocx.style.display = 'none';
    }

    loadStageProfilesList();

  } catch (err) {
    box.innerHTML = `
      <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--accent-rose); gap: 12px; padding: 20px; text-align: center;">
        <div style="font-size: 3rem;">⚠️</div>
        <p style="font-weight: 600;">${err.message}</p>
        <p style="font-size: 0.85rem; color: var(--text-muted);">Comprueba que haya actividades registradas para esta fecha en Intervals.icu.</p>
      </div>
    `;
    showToast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<span>⚡</span><span>Analizar y Generar Perfil</span>`;
  }
});

// =============================================================================
// MÓDULO 3: POWER & LOAD REPORTS
// =============================================================================

async function loadPowerReport() {
  const grupoVal = document.getElementById('report-select-group')?.value;
  const dias = document.getElementById('report-select-days-peaks')?.value || 30;
  const diasCarga = document.getElementById('report-select-days-load')?.value || 60;

  const tbodyPeaks = document.getElementById('tbody-peaks-report');
  const tbodyLoad = document.getElementById('tbody-load-report');
  if (tbodyPeaks) tbodyPeaks.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-dim);">Consultando picos en Intervals.icu...</td></tr>`;

  try {
    let url = `/api/power-report/data?dias=${dias}&dias_carga=${diasCarga}`;
    if (grupoVal) {
      if (grupoVal.startsWith('race:')) {
        url += `&carrera_id=${encodeURIComponent(grupoVal.replace('race:', ''))}`;
      } else {
        url += `&grupo=${encodeURIComponent(grupoVal)}`;
      }
    }

    const res = await fetch(url);
    if (!res.ok) throw new Error('Error al obtener datos del informe');
    const data = await res.json();

    // 1. Tabla de Picos
    if (data.peaks_table && data.peaks_table.length > 0) {
      tbodyPeaks.innerHTML = data.peaks_table.map(r => `
        <tr>
          <td><strong>${r['Ciclista'] || r['Name'] || 'Atleta'}</strong></td>
          <td class="mono">${r['5s (W)'] || '-'}</td>
          <td class="mono" style="color: var(--accent-cyan);">${r['5s (W/kg)'] || '-'}</td>
          <td class="mono">${r['1m (W)'] || '-'}</td>
          <td class="mono" style="color: var(--accent-cyan);">${r['1m (W/kg)'] || '-'}</td>
          <td class="mono">${r['5m (W)'] || '-'}</td>
          <td class="mono" style="color: var(--accent-cyan);">${r['5m (W/kg)'] || '-'}</td>
          <td class="mono">${r['20m (W)'] || '-'}</td>
          <td class="mono" style="color: var(--accent-cyan);">${r['20m (W/kg)'] || '-'}</td>
        </tr>
      `).join('');

      renderPeaksChart(data.peaks_table);
    } else {
      tbodyPeaks.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-dim);">No se encontraron picos recientes para los ciclistas del grupo.</td></tr>`;
    }

    // 2. Tabla de Carga
    if (data.metrics_table && data.metrics_table.length > 0) {
      tbodyLoad.innerHTML = data.metrics_table.map(r => `
        <tr>
          <td><strong>${r['athlete_name'] || 'Atleta'}</strong></td>
          <td class="mono" style="font-weight: 600; color: var(--accent-cyan);">${r['ctl'] ?? '-'}</td>
          <td class="mono" style="color: var(--accent-rose);">${r['atl'] ?? '-'}</td>
          <td class="mono" style="color: ${parseFloat(r['tsb']) >= 0 ? 'var(--accent-emerald)' : 'var(--accent-amber)'}; font-weight: 600;">${r['tsb'] ?? '-'}</td>
          <td class="mono">${r['ramp_rate'] ?? '-'}</td>
          <td class="mono">${r['weekly_tss'] ? Math.round(r['weekly_tss']) : '-'}</td>
        </tr>
      `).join('');
    } else {
      tbodyLoad.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-dim);">Sin datos de carga registrados.</td></tr>`;
    }

  } catch (err) {
    console.error(err);
    showToast('Error al cargar datos del informe', 'error');
  }
}

document.getElementById('btn-load-power-report')?.addEventListener('click', loadPowerReport);

function renderPeaksChart(peaksData) {
  const ctx = document.getElementById('chart-peaks-comparison');
  if (!ctx) return;

  if (AppState.peaksChart) {
    AppState.peaksChart.destroy();
  }

  const labels = peaksData.map(d => d['Ciclista'] || d['Name'] || 'Atleta');
  const data5m = peaksData.map(d => parseFloat(d['5m (W/kg)']) || 0);
  const data20m = peaksData.map(d => parseFloat(d['20m (W/kg)']) || 0);

  const textColor = getChartTextColor();
  const gridColor = getChartGridColor();

  AppState.peaksChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {
          label: '5m (W/kg) - VO2máx',
          data: data5m,
          backgroundColor: 'rgba(2, 132, 199, 0.75)',
          borderColor: '#0284c7',
          borderWidth: 1,
          borderRadius: 6
        },
        {
          label: '20m (W/kg) - Umbral / FTP',
          data: data20m,
          backgroundColor: 'rgba(5, 150, 105, 0.75)',
          borderColor: '#059669',
          borderWidth: 1,
          borderRadius: 6
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: textColor } }
      },
      scales: {
        x: { ticks: { color: textColor }, grid: { color: gridColor } },
        y: { 
          title: { display: true, text: 'W/kg', color: textColor },
          ticks: { color: textColor }, 
          grid: { color: gridColor },
          suggestedMin: 3.5
        }
      }
    }
  });
}

// Exportación en 1 clic PDF y Word
document.getElementById('btn-export-power-pdf')?.addEventListener('click', () => triggerPowerExport('pdf'));
document.getElementById('btn-export-power-docx')?.addEventListener('click', () => triggerPowerExport('docx'));

async function triggerPowerExport(formato) {
  const grupoVal = document.getElementById('report-select-group')?.value;
  const dias = document.getElementById('report-select-days-peaks')?.value || 30;
  const diasCarga = document.getElementById('report-select-days-load')?.value || 60;

  showToast(`Generando informe ejecutivo en ${formato.toUpperCase()}...`, 'info');

  try {
    const payload = {
      dias: parseInt(dias),
      dias_carga: parseInt(diasCarga),
      formato: formato
    };
    if (grupoVal) {
      if (grupoVal.startsWith('race:')) {
        payload.carrera_id = grupoVal.replace('race:', '');
      } else {
        payload.grupo = parseInt(grupoVal);
      }
    }

    const res = await fetch('/api/power-report/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error('Error al exportar informe');
    const data = await res.json();

    if (data.archivos && data.archivos[formato]) {
      showToast(`¡Informe ${formato.toUpperCase()} listo para descargar!`, 'success');
      window.open(data.archivos[formato], '_blank');
    }
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// =============================================================================
// MÓDULO 4: RÉCORDS Y FATIGA (SEASON BESTS + kJ)
// =============================================================================

async function loadRecordsView() {
  const selectAthlete = document.getElementById('records-select-athlete');
  if (!selectAthlete) return;

  if (selectAthlete.options.length <= 1) {
    const res = await fetch('/api/athletes');
    const athletes = await res.json();
    selectAthlete.innerHTML = athletes.map(a => `
      <option value="${a.intervals_id}">${a.name} (${a.intervals_id})</option>
    `).join('');
  }

  loadAthleteRecords();
}

async function loadAthleteRecords() {
  const selectAthlete = document.getElementById('records-select-athlete');
  const athleteId = selectAthlete?.value;
  if (!athleteId) return;

  const temporada = document.getElementById('records-select-season')?.value || '';
  const isFatigue = document.getElementById('toggle-fatigue-comparison')?.checked;

  const tbody = document.getElementById('tbody-season-records');
  tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-dim);">Consultando curva récord y kilojulios previos...</td></tr>`;

  try {
    if (isFatigue) {
      // Vista comparativa de fatiga
      const res = await fetch(`/api/fatigue-curve/${athleteId}?umbral_kj=2000${temporada ? `&temporada=${temporada}` : ''}`);
      const data = await res.json();

      document.getElementById('records-chart-subtitle').textContent = `Comparativa Fresco (<2000 kJ) vs Bajo Fatiga (≥2000 kJ)`;

      // Render tabla fatiga
      tbody.innerHTML = data.comparison.map(c => `
        <tr>
          <td><strong>${c.duracion_str}</strong></td>
          <td class="mono">${c.watts_fresco ? `${c.watts_fresco} W` : '-'}</td>
          <td class="mono" style="color: var(--accent-cyan);">${c.wkg_fresco ? `${c.wkg_fresco} W/kg` : '-'}</td>
          <td class="mono" style="color: var(--accent-amber); font-weight: 600;">${c.watts_fatiga ? `${c.watts_fatiga} W` : '-'}</td>
          <td class="mono" style="color: var(--accent-amber);">${c.wkg_fatiga ? `${c.wkg_fatiga} W/kg` : '-'}</td>
          <td colspan="2" class="mono" style="color: ${c.perdida_pct < 0 ? 'var(--accent-rose)' : 'var(--accent-emerald)'}; font-weight: 700;">
            ${c.perdida_pct !== null ? `${c.perdida_pct}%` : '-'}
          </td>
          <td colspan="3" style="color: var(--text-dim); font-size: 0.82rem;">Umbral: 2.000 kJ</td>
        </tr>
      `).join('');

      renderFatigueCurveChart(data.comparison);

    } else {
      // Vista estándar con todos los kJ
      const res = await fetch(`/api/season-bests/${athleteId}?temporada=${temporada}`);
      const data = await res.json();

      const athleteName = selectAthlete.options[selectAthlete.selectedIndex].text;
      document.getElementById('records-chart-subtitle').textContent = `${athleteName} - ${temporada ? `Temporada ${temporada}` : 'Histórico Global'}`;

      if (!data.records || data.records.length === 0) {
        tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-dim);">No se encontraron registros de récord para este atleta.</td></tr>`;
        return;
      }

      tbody.innerHTML = data.records.map(r => `
        <tr>
          <td><strong>${r.duracion_str}</strong></td>
          <td class="mono" style="font-weight: 700; color: #fff;">${r.max_watts} W</td>
          <td class="mono" style="color: var(--accent-cyan); font-weight: 600;">${r.w_kg}</td>
          <td class="mono" style="color: var(--accent-amber); font-weight: 600;">${r.kj_previos.toLocaleString()} kJ</td>
          <td class="mono">${r.kjkg_previos}</td>
          <td class="mono">${r.kj_esfuerzo.toLocaleString()} kJ</td>
          <td class="mono" style="color: var(--accent-emerald); font-weight: 700;">${r.kj_totales.toLocaleString()} kJ</td>
          <td class="mono" style="color: var(--text-muted);">${r.momento_carrera}</td>
          <td class="mono" style="font-size: 0.82rem;">${r.fecha}</td>
          <td style="font-size: 0.82rem; color: var(--text-dim);">${r.nombre_carrera || '-'}</td>
        </tr>
      `).join('');

      renderMMPChart(data.records);
    }
  } catch (err) {
    console.error(err);
    showToast('Error al cargar mejores números', 'error');
  }
}

document.getElementById('btn-load-records')?.addEventListener('click', loadAthleteRecords);
document.getElementById('toggle-fatigue-comparison')?.addEventListener('change', loadAthleteRecords);

function renderMMPChart(records) {
  const ctx = document.getElementById('chart-mmp-curve');
  if (!ctx) return;

  if (AppState.mmpChart) {
    AppState.mmpChart.destroy();
  }

  const labels = records.map(r => r.duracion_str);
  const watts = records.map(r => r.max_watts);
  const wkg = records.map(r => r.w_kg);
  const kjPrevios = records.map(r => r.kj_previos);

  const textColor = getChartTextColor();
  const gridColor = getChartGridColor();

  AppState.mmpChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Potencia Máxima (W)',
          data: watts,
          borderColor: '#0284c7',
          backgroundColor: 'rgba(2, 132, 199, 0.12)',
          fill: true,
          tension: 0.3,
          pointRadius: 5,
          pointHoverRadius: 8,
          pointBackgroundColor: '#0284c7'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: textColor } },
        tooltip: {
          callbacks: {
            afterLabel: function(context) {
              const idx = context.dataIndex;
              return [
                `W/kg: ${wkg[idx]}`,
                `kJ Previos (Fatiga): ${kjPrevios[idx]} kJ`,
                `Momento: ${records[idx].momento_carrera}`
              ];
            }
          }
        }
      },
      scales: {
        x: { ticks: { color: textColor }, grid: { color: gridColor } },
        y: { 
          title: { display: true, text: 'Vatios (W)', color: textColor },
          ticks: { color: textColor }, 
          grid: { color: gridColor } 
        }
      }
    }
  });
}

function renderFatigueCurveChart(comparison) {
  const ctx = document.getElementById('chart-mmp-curve');
  if (!ctx) return;

  if (AppState.mmpChart) {
    AppState.mmpChart.destroy();
  }

  const textColor = getChartTextColor();
  const gridColor = getChartGridColor();

  const labels = comparison.map(c => c.duracion_str);
  const wattsFresco = comparison.map(c => c.watts_fresco);
  const wattsFatiga = comparison.map(c => c.watts_fatiga);

  AppState.mmpChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Fresco (< 2000 kJ)',
          data: wattsFresco,
          borderColor: '#059669',
          backgroundColor: 'rgba(5, 150, 105, 0.1)',
          tension: 0.3,
          pointRadius: 5,
          pointHoverRadius: 8,
          pointBackgroundColor: '#059669'
        },
        {
          label: 'Bajo Fatiga (≥ 2000 kJ)',
          data: wattsFatiga,
          borderColor: '#d97706',
          backgroundColor: 'rgba(217, 119, 6, 0.1)',
          tension: 0.3,
          pointRadius: 5,
          pointHoverRadius: 8,
          pointBackgroundColor: '#d97706'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: textColor } }
      },
      scales: {
        x: { ticks: { color: textColor }, grid: { color: gridColor } },
        y: { 
          title: { display: true, text: 'Vatios (W)', color: textColor },
          ticks: { color: textColor }, 
          grid: { color: gridColor } 
        }
      }
    }
  });
}

// =============================================================================
// MÓDULO 5: ADMINISTRACIÓN (CRUD CICLISTAS & CARRERAS)
// =============================================================================

async function loadAthletesAdmin() {
  const tbody = document.getElementById('tbody-athletes-admin');
  const checklistContainer = document.getElementById('athletes-checklist-container');
  if (!tbody) return;

  try {
    const res = await fetch('/api/athletes');
    const athletes = await res.json();
    AppState.athletes = athletes;

    tbody.innerHTML = athletes.map(a => `
      <tr>
        <td><strong>${a.name}</strong></td>
        <td class="mono">${a.intervals_id}</td>
        <td class="mono">${a.weight} kg</td>
        <td class="mono">${a.ftp} W</td>
        <td class="mono">${a.biela} mm</td>
        <td>
          <span class="badge badge-race-${a.carrera}">
            ${a.carrera === 1 ? 'Carrera 1' : (a.carrera === 2 ? 'Carrera 2' : 'Descanso')}
          </span>
        </td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="openEditAthleteModal('${a.intervals_id}')">✏️ Editar</button>
          <button class="btn btn-danger btn-sm" onclick="deleteAthletePrompt('${a.intervals_id}', '${a.name}')">🗑️</button>
        </td>
      </tr>
    `).join('');

    // Convocatoria checklist
    if (checklistContainer) {
      checklistContainer.innerHTML = athletes.map(a => `
        <label style="background: var(--checklist-item-bg); padding: 10px 14px; border-radius: var(--radius-md); border: 1px solid var(--border-subtle); display: flex; align-items: center; gap: 10px; cursor: pointer;">
          <input type="checkbox" value="${a.intervals_id}" class="chk-assign-athlete" ${a.carrera > 0 ? 'checked' : ''} style="accent-color: var(--accent-cyan);">
          <div>
            <div style="font-weight: 600; font-size: 0.9rem;">${a.name}</div>
            <div style="font-size: 0.75rem; color: var(--text-dim);">${a.intervals_id} (Grupo ${a.carrera})</div>
          </div>
        </label>
      `).join('');
    }

  } catch (err) {
    showToast('Error al cargar lista de ciclistas', 'error');
  }
}

async function loadRacesAdmin() {
  const tbody = document.getElementById('tbody-races-admin');
  if (!tbody) return;

  try {
    const res = await fetch('/api/races');
    if (!res.ok) throw new Error('Error al cargar calendario de carreras');
    AppState.racesCalendar = await res.json();
    renderRacesAdminTable();
  } catch (err) {
    console.error(err);
    tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--accent-rose); padding: 20px;">Error al cargar las carreras del calendario.</td></tr>`;
  }
}

function renderRacesAdminTable() {
  const tbody = document.getElementById('tbody-races-admin');
  if (!tbody) return;

  let races = AppState.racesCalendar || [];

  if (AppState.raceFilter && AppState.raceFilter !== 'all') {
    races = races.filter(r => r.estado === AppState.raceFilter);
  }

  if (races.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-dim); padding: 24px;">No se encontraron competiciones para este filtro.</td></tr>`;
    return;
  }

  tbody.innerHTML = races.map(r => {
    const flag = getCountryFlag(r.pais);
    let estadoBadge = '<span class="badge-status badge-status-upcoming">📅 Próxima</span>';
    if (r.estado === 'en_curso') {
      estadoBadge = `<span class="badge badge-race-1">🟢 En Curso (${r.etapa_actual || 1}/${r.total_etapas || r.num_etapas || 1})</span>`;
    } else if (r.estado === 'finalizada') {
      estadoBadge = '<span class="badge-status badge-status-finished">🏁 Finalizada</span>';
    }

    const convocados = r.convocados || [];
    let convocadosHtml = '';
    if (convocados.length > 0) {
      const visible = convocados.slice(0, 4);
      convocadosHtml = `<div class="convocados-tag-list">` +
        visible.map(c => `<span class="convocado-tag">${c.name || c.atleta_id}</span>`).join('') +
        (convocados.length > 4 ? `<span class="convocado-tag" style="background: var(--bg-hover); color: var(--accent-cyan);">+${convocados.length - 4} más</span>` : '') +
        `</div>`;
    } else {
      convocadosHtml = `<span style="color: var(--text-dim); font-size: 0.8rem;">Sin convocados</span>`;
    }

    const distKm = r.dist_total_km != null ? Math.round(r.dist_total_km).toLocaleString() + ' km' : '-';
    const totalKj = r.kj_totales != null ? Math.round(r.kj_totales).toLocaleString() + ' kJ' : '-';
    const numEtapas = r.total_etapas || r.num_etapas || '-';

    return `
      <tr>
        <td>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 1.2rem;">${flag}</span>
            <div>
              <strong>${r.nombre_carrera}</strong>
              <div class="mono" style="font-size: 0.74rem; color: var(--text-dim);">${r.carrera_id}</div>
            </div>
          </div>
        </td>
        <td>
          <span class="badge-uci">${r.categoria || 'UCI 2.Pro'}</span>
          <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 2px;">${r.pais || 'España'}</div>
        </td>
        <td>
          <div class="mono" style="font-size: 0.82rem;">${r.fecha_inicio}</div>
          <div class="mono" style="font-size: 0.82rem; color: var(--text-dim);">al ${r.fecha_fin}</div>
        </td>
        <td>${estadoBadge}</td>
        <td>${convocadosHtml}</td>
        <td><span class="badge badge-race-1">${numEtapas} etapas</span></td>
        <td class="mono">${distKm}</td>
        <td class="mono" style="color: var(--accent-cyan); font-weight: 600;">${totalKj}</td>
        <td>
          <div style="display: flex; gap: 6px; flex-wrap: wrap;">
            <button class="btn btn-secondary btn-sm" style="padding: 3px 8px; font-size: 0.78rem;" onclick="openConvocatoriaModal('${r.carrera_id}')" title="Ajustar convocatoria">
              <span>👥</span> Convocatoria
            </button>
            <button class="btn btn-secondary btn-sm" style="padding: 3px 8px; font-size: 0.78rem;" onclick="openRaceHistoryModal('${r.carrera_id}', '${escapeJs(r.nombre_carrera)}')" title="Ver histórico">
              <span>📊</span> Histórico
            </button>
            <button class="btn btn-secondary btn-sm" style="padding: 3px 8px; font-size: 0.78rem;" onclick="openEditRaceModal('${r.carrera_id}')" title="Editar datos">
              <span>✏️</span>
            </button>
            <button class="btn btn-danger btn-sm" style="padding: 3px 8px; font-size: 0.78rem;" onclick="deleteRacePrompt('${r.carrera_id}', '${escapeJs(r.nombre_carrera)}')" title="Eliminar carrera">
              <span>🗑️</span>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

// -----------------------------------------------------------------------------
// Modales de Gestión de Carreras y Convocatorias CRUD
// -----------------------------------------------------------------------------

function renderAthletesChecklist(containerId, checkboxClass, selectedIds = [], counterId = null) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const selectedSet = new Set((selectedIds || []).map(String));
  const athletes = AppState.athletes || [];

  if (athletes.length === 0) {
    container.innerHTML = `<div style="grid-column: 1 / -1; color: var(--text-dim); padding: 8px;">No hay ciclistas dados de alta en el equipo.</div>`;
    if (counterId) document.getElementById(counterId).textContent = '0 seleccionados';
    return;
  }

  container.innerHTML = athletes.map(a => {
    const isChecked = selectedSet.has(String(a.intervals_id));
    return `
      <label class="convocado-chk-item">
        <input type="checkbox" value="${a.intervals_id}" class="${checkboxClass}" ${isChecked ? 'checked' : ''}>
        <div>
          <div style="font-weight: 600; font-size: 0.88rem;">${a.name}</div>
          <div style="font-size: 0.74rem; color: var(--text-dim);">${a.intervals_id} · ${a.weight || 70}kg · ${a.ftp || 380}W</div>
        </div>
      </label>
    `;
  }).join('');

  const updateCounter = () => {
    if (!counterId) return;
    const count = container.querySelectorAll(`.${checkboxClass}:checked`).length;
    const el = document.getElementById(counterId);
    if (el) el.textContent = `${count} seleccionado${count === 1 ? '' : 's'}`;
  };

  container.querySelectorAll(`.${checkboxClass}`).forEach(chk => {
    chk.addEventListener('change', updateCounter);
  });

  updateCounter();
}

function openCreateRaceModal() {
  document.getElementById('modal-rf-title').textContent = 'Dar de Alta Carrera';
  document.getElementById('modal-rf-subtitle').textContent = 'Configura las fechas de competición, categoría y la nómina de ciclistas convocados.';
  document.getElementById('form-rf-carrera-id').value = '';
  document.getElementById('form-rf-nombre').value = '';
  document.getElementById('form-rf-slug').value = '';
  document.getElementById('form-rf-categoria').value = 'UCI 2.Pro';
  document.getElementById('form-rf-pais').value = 'España';
  document.getElementById('form-rf-etapas').value = '5';
  document.getElementById('form-rf-etapa-actual').value = '0';
  document.getElementById('form-rf-notas').value = '';

  const today = new Date().toISOString().slice(0, 10);
  document.getElementById('form-rf-fecha-inicio').value = today;
  document.getElementById('form-rf-fecha-fin').value = today;

  renderAthletesChecklist('form-rf-athletes-checklist', 'chk-rf-athlete', [], 'rf-convocados-count');
  document.getElementById('modal-race-form')?.classList.add('active');
}

async function openEditRaceModal(carreraId) {
  try {
    const res = await fetch(`/api/races/${encodeURIComponent(carreraId)}`);
    if (!res.ok) throw new Error('No se pudo obtener información de la carrera');
    const r = await res.json();

    document.getElementById('modal-rf-title').textContent = `Editar Carrera: ${r.nombre_carrera}`;
    document.getElementById('modal-rf-subtitle').textContent = `Identificador: ${r.carrera_id}`;
    document.getElementById('form-rf-carrera-id').value = r.carrera_id;
    document.getElementById('form-rf-nombre').value = r.nombre_carrera || '';
    document.getElementById('form-rf-slug').value = r.carrera_id || '';
    document.getElementById('form-rf-categoria').value = r.categoria || 'UCI 2.Pro';
    document.getElementById('form-rf-pais').value = r.pais || 'España';
    document.getElementById('form-rf-etapas').value = r.total_etapas || 5;
    document.getElementById('form-rf-etapa-actual').value = r.etapa_actual || 0;
    document.getElementById('form-rf-fecha-inicio').value = r.fecha_inicio || '';
    document.getElementById('form-rf-fecha-fin').value = r.fecha_fin || '';
    document.getElementById('form-rf-notas').value = r.notas || '';

    const convocadoIds = (r.convocados || []).map(c => c.atleta_id);
    renderAthletesChecklist('form-rf-athletes-checklist', 'chk-rf-athlete', convocadoIds, 'rf-convocados-count');

    document.getElementById('modal-race-form')?.classList.add('active');
  } catch (err) {
    console.error(err);
    showToast(err.message, 'error');
  }
}

function closeRaceFormModal() {
  document.getElementById('modal-race-form')?.classList.remove('active');
}

document.getElementById('form-race-crud')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const carreraId = document.getElementById('form-rf-carrera-id').value.trim();
  const isEdit = Boolean(carreraId);

  const selectedAthletes = [];
  document.querySelectorAll('.chk-rf-athlete:checked').forEach(chk => {
    selectedAthletes.push(chk.value);
  });

  const payload = {
    nombre_carrera: document.getElementById('form-rf-nombre').value.trim(),
    carrera_id: document.getElementById('form-rf-slug').value.trim() || undefined,
    categoria: document.getElementById('form-rf-categoria').value,
    pais: document.getElementById('form-rf-pais').value.trim(),
    total_etapas: parseInt(document.getElementById('form-rf-etapas').value) || 1,
    etapa_actual: parseInt(document.getElementById('form-rf-etapa-actual').value) || 0,
    fecha_inicio: document.getElementById('form-rf-fecha-inicio').value,
    fecha_fin: document.getElementById('form-rf-fecha-fin').value,
    notas: document.getElementById('form-rf-notas').value.trim() || undefined,
    atletas_ids: selectedAthletes
  };

  try {
    let res;
    if (isEdit) {
      res = await fetch(`/api/races/${encodeURIComponent(carreraId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    } else {
      res = await fetch('/api/races', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    }

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Error al guardar la carrera');
    }

    const data = await res.json();
    showToast(data.message || (isEdit ? 'Carrera actualizada con éxito' : 'Carrera registrada con éxito'), 'success');
    closeRaceFormModal();
    loadRacesAdmin();
    loadDashboardData();
  } catch (err) {
    console.error(err);
    showToast(err.message, 'error');
  }
});

// Modal de Convocatoria Rápida
async function openConvocatoriaModal(carreraId) {
  try {
    const res = await fetch(`/api/races/${encodeURIComponent(carreraId)}/convocatoria`);
    if (!res.ok) throw new Error('Error al cargar la convocatoria');
    const data = await res.json();

    document.getElementById('form-cq-carrera-id').value = carreraId;
    const raceObj = (AppState.racesCalendar || []).find(r => r.carrera_id === carreraId);
    const raceName = raceObj ? raceObj.nombre_carrera : carreraId;
    document.getElementById('modal-cq-title').textContent = `Convocatoria: ${raceName}`;
    document.getElementById('modal-cq-subtitle').textContent = `Marca los ciclistas convocados para competir en esta carrera.`;

    const convocadoIds = (data.convocados || []).map(c => c.atleta_id);
    renderAthletesChecklist('cq-athletes-checklist', 'chk-cq-athlete', convocadoIds, 'cq-selected-count');

    document.getElementById('modal-convocatoria-quick')?.classList.add('active');
  } catch (err) {
    console.error(err);
    showToast(err.message, 'error');
  }
}

function closeConvocatoriaModal() {
  document.getElementById('modal-convocatoria-quick')?.classList.remove('active');
}

document.getElementById('form-convocatoria-quick')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const carreraId = document.getElementById('form-cq-carrera-id').value.trim();
  if (!carreraId) return;

  const selectedAthletes = [];
  document.querySelectorAll('.chk-cq-athlete:checked').forEach(chk => {
    selectedAthletes.push(chk.value);
  });

  try {
    const res = await fetch(`/api/races/${encodeURIComponent(carreraId)}/convocatoria`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ athlete_ids: selectedAthletes })
    });

    if (!res.ok) throw new Error('Error al guardar convocatoria');
    const data = await res.json();
    showToast(data.message || 'Convocatoria actualizada con éxito', 'success');
    closeConvocatoriaModal();
    loadRacesAdmin();
    loadDashboardData();
  } catch (err) {
    console.error(err);
    showToast(err.message, 'error');
  }
});

async function deleteRacePrompt(carreraId, name) {
  if (!confirm(`¿Estás seguro de eliminar la carrera '${name}' (${carreraId}) y su historial de convocatoria?`)) return;

  try {
    const res = await fetch(`/api/races/${encodeURIComponent(carreraId)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Error al eliminar la carrera');
    showToast(`Carrera '${name}' eliminada con éxito`, 'info');
    loadRacesAdmin();
    loadDashboardData();
  } catch (err) {
    console.error(err);
    showToast(err.message, 'error');
  }
}

// Modal de Atleta
function openAddAthleteModal() {
  document.getElementById('modal-athlete-title').textContent = 'Dar de Alta Nuevo Ciclista';
  document.getElementById('form-athlete-is-edit').value = '0';
  document.getElementById('form-athlete-id').readOnly = false;
  document.getElementById('form-athlete-id').value = '';
  document.getElementById('form-athlete-name').value = '';
  document.getElementById('form-athlete-weight').value = '70';
  document.getElementById('form-athlete-ftp').value = '380';
  document.getElementById('form-athlete-biela').value = '170';
  document.getElementById('form-athlete-carrera').value = '0';

  document.getElementById('modal-athlete').classList.add('active');
}

function openEditAthleteModal(athleteId) {
  const athlete = AppState.athletes.find(a => a.intervals_id === athleteId);
  if (!athlete) return;

  document.getElementById('modal-athlete-title').textContent = `Editar Ciclista: ${athlete.name}`;
  document.getElementById('form-athlete-is-edit').value = '1';
  document.getElementById('form-athlete-id').value = athlete.intervals_id;
  document.getElementById('form-athlete-id').readOnly = true;
  document.getElementById('form-athlete-name').value = athlete.name;
  document.getElementById('form-athlete-weight').value = athlete.weight;
  document.getElementById('form-athlete-ftp').value = athlete.ftp;
  document.getElementById('form-athlete-biela').value = athlete.biela;
  document.getElementById('form-athlete-carrera').value = athlete.carrera;

  document.getElementById('modal-athlete').classList.add('active');
}

function closeAthleteModal() {
  document.getElementById('modal-athlete').classList.remove('active');
}

document.getElementById('btn-open-add-athlete-modal')?.addEventListener('click', openAddAthleteModal);
document.getElementById('btn-close-athlete-modal')?.addEventListener('click', closeAthleteModal);
document.getElementById('btn-cancel-athlete-modal')?.addEventListener('click', closeAthleteModal);

document.getElementById('form-athlete')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const isEdit = document.getElementById('form-athlete-is-edit').value === '1';
  const aid = document.getElementById('form-athlete-id').value.trim();

  const payload = {
    name: document.getElementById('form-athlete-name').value.trim(),
    weight: parseFloat(document.getElementById('form-athlete-weight').value),
    ftp: parseFloat(document.getElementById('form-athlete-ftp').value),
    biela: parseFloat(document.getElementById('form-athlete-biela').value),
    carrera: parseInt(document.getElementById('form-athlete-carrera').value)
  };

  try {
    let res;
    if (isEdit) {
      res = await fetch(`/api/athletes/${aid}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    } else {
      payload.intervals_id = aid;
      res = await fetch(`/api/athletes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    }

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Error en la operación');
    }

    showToast(isEdit ? 'Ciclista actualizado con éxito' : 'Ciclista dado de alta con éxito', 'success');
    closeAthleteModal();
    loadAthletesAdmin();
    loadDashboardData();

  } catch (err) {
    showToast(err.message, 'error');
  }
});

async function deleteAthletePrompt(athleteId, name) {
  if (!confirm(`¿Estás seguro de eliminar a ${name} (${athleteId}) del equipo?`)) return;

  try {
    const res = await fetch(`/api/athletes/${athleteId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Error al eliminar ciclista');
    showToast(`Ciclista ${name} eliminado`, 'info');
    loadAthletesAdmin();
    loadDashboardData();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// Guardar asignación de convocatorias masiva
document.getElementById('btn-save-race-assignment')?.addEventListener('click', async () => {
  const targetGroup = parseInt(document.getElementById('select-target-race-group').value);
  const selected = [];
  document.querySelectorAll('.chk-assign-athlete:checked').forEach(chk => {
    selected.push(chk.value);
  });

  if (selected.length === 0) {
    showToast('Selecciona al menos un ciclista para asignar', 'info');
    return;
  }

  try {
    const res = await fetch('/api/races/assign', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        carrera_id: targetGroup,
        athlete_ids: selected
      })
    });

    if (!res.ok) throw new Error('Error al guardar convocatoria');
    const data = await res.json();
    showToast(data.message, 'success');
    loadAthletesAdmin();
    loadDashboardData();
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// =============================================================================
// MÓDULO 6: CONFIGURACIÓN DE GRUPOS DE CARRERA Y CONSULTA DE HISTÓRICO DE VUELTA
// =============================================================================

// Modal Configuración de Carrera del Grupo
async function openRaceGroupConfigModal(groupNum) {
  try {
    const [resGroups, resRaces] = await Promise.all([
      fetch('/api/race-groups'),
      fetch('/api/races')
    ]);

    const groupsData = await resGroups.json();
    const races = await resRaces.json();
    const cfg = (groupsData && groupsData[String(groupNum)]) || {};

    document.getElementById('form-rg-grupo-id').value = groupNum;
    document.getElementById('modal-rg-title').textContent = `Configurar Carrera: Grupo ${groupNum}`;
    document.getElementById('form-rg-nombre').value = cfg.nombre_carrera || '';
    document.getElementById('form-rg-categoria').value = cfg.categoria || 'UCI 2.Pro';
    document.getElementById('form-rg-pais').value = cfg.pais || 'España';
    document.getElementById('form-rg-total-etapas').value = cfg.total_etapas || 5;
    document.getElementById('form-rg-etapa-actual').value = cfg.etapa_actual || 1;
    document.getElementById('form-rg-fecha-inicio').value = cfg.fecha_inicio || '';
    document.getElementById('form-rg-fecha-fin').value = cfg.fecha_fin || '';
    document.getElementById('form-rg-notas').value = cfg.notas || '';

    const selectLink = document.getElementById('form-rg-carrera-link');
    if (selectLink) {
      selectLink.innerHTML = `<option value="">-- Autodetección automática por corredor --</option>` +
        (races || []).map(r => `
          <option value="${r.carrera_id}" ${cfg.carrera_id_link === r.carrera_id ? 'selected' : ''}>
            ${r.nombre_carrera} (${r.fecha_inicio || ''})
          </option>
        `).join('');
      if (cfg.carrera_id_link) {
        selectLink.value = cfg.carrera_id_link;
      }
    }

    document.getElementById('modal-race-group-config').classList.add('active');
  } catch (err) {
    console.error(err);
    showToast('Error al abrir configuración del grupo', 'error');
  }
}

function closeRaceGroupConfigModal() {
  document.getElementById('modal-race-group-config')?.classList.remove('active');
}

document.getElementById('btn-close-rg-modal')?.addEventListener('click', closeRaceGroupConfigModal);
document.getElementById('btn-cancel-rg-modal')?.addEventListener('click', closeRaceGroupConfigModal);

document.getElementById('form-race-group-config')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const grupoId = document.getElementById('form-rg-grupo-id').value;
  const payload = {
    nombre_carrera: document.getElementById('form-rg-nombre').value.trim(),
    categoria: document.getElementById('form-rg-categoria').value,
    pais: document.getElementById('form-rg-pais').value.trim(),
    total_etapas: parseInt(document.getElementById('form-rg-total-etapas').value) || 5,
    etapa_actual: parseInt(document.getElementById('form-rg-etapa-actual').value) || 1,
    fecha_inicio: document.getElementById('form-rg-fecha-inicio').value || null,
    fecha_fin: document.getElementById('form-rg-fecha-fin').value || null,
    notas: document.getElementById('form-rg-notas').value.trim() || null,
    carrera_id_link: document.getElementById('form-rg-carrera-link').value || null
  };

  try {
    const res = await fetch(`/api/race-groups/${grupoId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Error al guardar configuración');
    }
    showToast(`Configuración de Grupo ${grupoId} actualizada con éxito`, 'success');
    closeRaceGroupConfigModal();
    loadDashboardData();
  } catch (err) {
    console.error(err);
    showToast(err.message, 'error');
  }
});

// Modal Histórico de Vuelta
async function openRaceHistoryModal(carreraId, carreraNombre) {
  if (!carreraId) {
    showToast('No se especificó la carrera a consultar', 'info');
    return;
  }

  const modal = document.getElementById('modal-race-history');
  if (!modal) return;
  modal.classList.add('active');

  const titleEl = document.getElementById('modal-rh-title');
  const subTitleEl = document.getElementById('modal-rh-subtitle');
  if (titleEl) titleEl.innerHTML = `<span>📊</span> Histórico de la Vuelta: ${carreraNombre || carreraId}`;
  if (subTitleEl) subTitleEl.textContent = `Identificador: ${carreraId} · Análisis etapa a etapa y balance final del equipo.`;

  switchRaceHistoryTab('rh-tab-stages');

  const tbodyStages = document.getElementById('tbody-rh-stages');
  const tbodySummary = document.getElementById('tbody-rh-summary');
  if (tbodyStages) tbodyStages.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--text-dim); padding: 24px;">Cargando histórico de etapas...</td></tr>`;
  if (tbodySummary) tbodySummary.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--text-dim); padding: 24px;">Cargando balance final...</td></tr>`;

  try {
    const [resStages, resSummary] = await Promise.all([
      fetch(`/api/races/${encodeURIComponent(carreraId)}/history`),
      fetch(`/api/races/${encodeURIComponent(carreraId)}/summary`)
    ]);

    if (!resStages.ok) throw new Error('Error al cargar etapas históricas');
    if (!resSummary.ok) throw new Error('Error al cargar balance de la vuelta');

    const dataStages = await resStages.json();
    const dataSummary = await resSummary.json();

    AppState.cachedRaceHistoryStages = dataStages.etapas || [];
    AppState.cachedRaceHistorySummary = dataSummary.resumen || [];

    const filterSelect = document.getElementById('select-rh-rider-filter');
    if (filterSelect) {
      const ridersMap = new Map();
      AppState.cachedRaceHistoryStages.forEach(e => {
        if (!ridersMap.has(e.atleta_id)) {
          ridersMap.set(e.atleta_id, e.atleta_nombre || e.atleta_id);
        }
      });
      let filterOpts = `<option value="">Todos los Ciclistas (${ridersMap.size})</option>`;
      ridersMap.forEach((nombre, id) => {
        filterOpts += `<option value="${id}">${nombre}</option>`;
      });
      filterSelect.innerHTML = filterOpts;
      filterSelect.value = '';
    }

    renderRaceHistoryStagesTable(AppState.cachedRaceHistoryStages);
    renderRaceHistorySummaryTable(AppState.cachedRaceHistorySummary);
    renderRaceHistoryChart(AppState.cachedRaceHistoryStages);

  } catch (err) {
    console.error(err);
    showToast(err.message, 'error');
    if (tbodyStages) tbodyStages.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--accent-rose); padding: 20px;">No se encontraron registros de etapas para esta carrera.</td></tr>`;
    if (tbodySummary) tbodySummary.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--accent-rose); padding: 20px;">No hay datos de balance disponibles.</td></tr>`;
  }
}

function closeRaceHistoryModal() {
  document.getElementById('modal-race-history')?.classList.remove('active');
}

document.getElementById('btn-close-rh-modal')?.addEventListener('click', closeRaceHistoryModal);
document.getElementById('btn-close-rh-modal-footer')?.addEventListener('click', closeRaceHistoryModal);

function switchRaceHistoryTab(tabId) {
  document.querySelectorAll('.modal-tab-btn').forEach(btn => {
    if (btn.getAttribute('data-modal-tab') === tabId) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  document.querySelectorAll('.rh-modal-tab-content').forEach(content => {
    if (content.id === tabId) {
      content.style.display = 'block';
    } else {
      content.style.display = 'none';
    }
  });

  if (tabId === 'rh-tab-chart' && AppState.raceHistoryChart) {
    setTimeout(() => {
      AppState.raceHistoryChart.resize();
    }, 50);
  }
}

function renderRaceHistoryStagesTable(etapas, riderFilter = '') {
  const tbody = document.getElementById('tbody-rh-stages');
  const countBadge = document.getElementById('rh-stages-badge-count');
  if (!tbody) return;

  let filtered = etapas || [];
  if (riderFilter) {
    filtered = filtered.filter(e => e.atleta_id === riderFilter);
  }

  if (countBadge) countBadge.textContent = `${filtered.length} registro(s)`;

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--text-dim); padding: 20px;">No hay etapas registradas para los criterios seleccionados.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(e => {
    const athName = e.atleta_nombre || e.nombre || e.atleta_id;
    const dist = e.distancia_km != null ? Number(e.distancia_km).toFixed(1) + ' km' : '-';
    const hours = (e.tiempo_movimiento_h ?? e.tiempo_mov_h) != null ? Number(e.tiempo_movimiento_h ?? e.tiempo_mov_h).toFixed(1) + ' h' : '-';
    const potMed = (e.potencia_media_w ?? e.pot_media_w) != null ? Math.round(e.potencia_media_w ?? e.pot_media_w) + ' W' : '-';
    const npW = (e.potencia_normalizada_w ?? e.np_w) != null ? Math.round(e.potencia_normalizada_w ?? e.np_w) + ' W' : '-';
    const kj = e.kj_total != null ? Math.round(e.kj_total).toLocaleString() : '-';
    const kjAcum = e.kj_acumulados != null ? Math.round(e.kj_acumulados).toLocaleString() + ' kJ' : '-';
    const tss = e.tss != null ? Math.round(e.tss) : '-';
    const tssAcum = (e.tss_acumulados ?? e.tss_acumulado) != null ? Math.round(e.tss_acumulados ?? e.tss_acumulado) : '-';

    return `
      <tr>
        <td><strong>${athName}</strong></td>
        <td><span class="badge badge-race-1">Etapa ${e.etapa_num}</span></td>
        <td class="mono">${e.fecha}</td>
        <td class="mono">${dist}</td>
        <td class="mono">${hours}</td>
        <td class="mono">${potMed}</td>
        <td class="mono">${npW}</td>
        <td class="mono">${kj}</td>
        <td class="mono" style="color: var(--accent-cyan); font-weight: 600;">${kjAcum}</td>
        <td class="mono">${tss}</td>
        <td class="mono" style="color: var(--accent-amber); font-weight: 600;">${tssAcum}</td>
      </tr>
    `;
  }).join('');
}

function renderRaceHistorySummaryTable(resumen) {
  const tbody = document.getElementById('tbody-rh-summary');
  if (!tbody) return;

  if (!resumen || resumen.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--text-dim); padding: 20px;">No hay datos de balance consolidado para esta carrera.</td></tr>`;
    return;
  }

  tbody.innerHTML = resumen.map(r => {
    const athName = r.atleta_nombre || r.nombre || r.atleta_id;
    const dist = (r.distancia_total_km ?? r.total_km) != null ? Number(r.distancia_total_km ?? r.total_km).toFixed(1) + ' km' : '-';
    const dPlus = (r.desnivel_total_m ?? r.total_desnivel_m) != null ? Math.round(r.desnivel_total_m ?? r.total_desnivel_m).toLocaleString() + ' m' : '-';
    const hours = (r.horas_totales ?? r.total_horas) != null ? Number(r.horas_totales ?? r.total_horas).toFixed(1) + ' h' : '-';
    const kj = (r.kj_totales ?? r.total_kj) != null ? Math.round(r.kj_totales ?? r.total_kj).toLocaleString() + ' kJ' : '-';
    const kjKg = (r.kj_kg_total ?? r.total_kj_kg) != null ? Number(r.kj_kg_total ?? r.total_kj_kg).toFixed(1) + ' kJ/kg' : '-';
    const kjKgH = r.media_kj_kg_h != null ? Number(r.media_kj_kg_h).toFixed(1) : '-';
    const tss = (r.tss_total ?? r.total_tss) != null ? Math.round(r.tss_total ?? r.total_tss) : '-';
    const npW = (r.np_media ?? r.media_np_w) != null ? Math.round(r.np_media ?? r.media_np_w) + ' W' : '-';
    const ifVal = (r.if_medio ?? r.media_if) != null ? Number(r.if_medio ?? r.media_if).toFixed(2) : '-';

    return `
      <tr>
        <td><strong>${athName}</strong></td>
        <td><span class="badge badge-race-1">${r.etapas_disputadas} etapa(s)</span></td>
        <td class="mono">${dist}</td>
        <td class="mono">${dPlus}</td>
        <td class="mono">${hours}</td>
        <td class="mono" style="color: var(--accent-cyan); font-weight: 700;">${kj}</td>
        <td class="mono">${kjKg}</td>
        <td class="mono">${kjKgH}</td>
        <td class="mono" style="color: var(--accent-rose); font-weight: 600;">${tss}</td>
        <td class="mono">${npW}</td>
        <td class="mono">${ifVal}</td>
      </tr>
    `;
  }).join('');
}

function renderRaceHistoryChart(etapas) {
  const canvas = document.getElementById('chart-rh-accumulated');
  if (!canvas) return;

  if (AppState.raceHistoryChart) {
    AppState.raceHistoryChart.destroy();
    AppState.raceHistoryChart = null;
  }

  if (!etapas || etapas.length === 0) return;

  const stageNums = [...new Set(etapas.map(e => e.etapa_num))].sort((a, b) => a - b);
  const labels = ['Salida (0)', ...stageNums.map(n => `Etapa ${n}`)];

  const athletesMap = {};
  etapas.forEach(e => {
    const id = e.atleta_id;
    if (!athletesMap[id]) {
      athletesMap[id] = {
        name: e.atleta_nombre || id,
        stages: {}
      };
    }
    athletesMap[id].stages[e.etapa_num] = Math.round(e.kj_acumulados || 0);
  });

  const palette = [
    '#38bdf8', '#10b981', '#f59e0b', '#f43f5e', '#a855f7',
    '#06b6d4', '#ec4899', '#84cc16', '#6366f1', '#14b8a6'
  ];

  let colorIdx = 0;
  const datasets = Object.keys(athletesMap).map(id => {
    const ath = athletesMap[id];
    const color = palette[colorIdx % palette.length];
    colorIdx++;

    const data = [0];
    let lastVal = 0;
    stageNums.forEach(n => {
      if (ath.stages[n] !== undefined) {
        lastVal = ath.stages[n];
      }
      data.push(lastVal);
    });

    return {
      label: ath.name,
      data: data,
      borderColor: color,
      backgroundColor: color + '22',
      borderWidth: 2.5,
      tension: 0.25,
      pointRadius: 4,
      pointHoverRadius: 6,
      pointBackgroundColor: color
    };
  });

  const textColor = getChartTextColor();
  const gridColor = getChartGridColor();

  AppState.raceHistoryChart = new Chart(canvas, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'top',
          labels: { color: textColor, boxWidth: 12, padding: 14 }
        },
        tooltip: {
          callbacks: {
            label: (context) => `${context.dataset.label}: ${context.parsed.y.toLocaleString()} kJ acumulados`
          }
        }
      },
      scales: {
        x: {
          ticks: { color: textColor },
          grid: { color: gridColor }
        },
        y: {
          title: { display: true, text: 'Kilojulios Acumulados (kJ)', color: textColor },
          ticks: {
            color: textColor,
            callback: (val) => val.toLocaleString() + ' kJ'
          },
          grid: { color: gridColor }
        }
      }
    }
  });
}

// =============================================================================
// INICIALIZACIÓN AL CARGAR LA PÁGINA
// =============================================================================

document.addEventListener('DOMContentLoaded', () => {
  // Inicializar controlador de tema
  initTheme();

  // Configurar listeners de navegación
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      const tab = item.getAttribute('data-tab');
      navigateToTab(tab);
    });
  });

  // Configurar tabs del modal de histórico de vuelta
  document.querySelectorAll('.modal-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tabId = btn.getAttribute('data-modal-tab');
      if (tabId) switchRaceHistoryTab(tabId);
    });
  });

  // Listener para filtro de ciclista en modal de histórico
  document.getElementById('select-rh-rider-filter')?.addEventListener('change', (e) => {
    renderRaceHistoryStagesTable(AppState.cachedRaceHistoryStages, e.target.value);
  });

  // Configurar listeners de filtros de calendario de carreras
  document.querySelectorAll('.filter-pill-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-pill-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      AppState.raceFilter = btn.getAttribute('data-race-filter') || 'all';
      renderRacesAdminTable();
    });
  });

  // Botones para modal de alta / edición de carrera
  document.getElementById('btn-open-create-race-modal')?.addEventListener('click', openCreateRaceModal);
  document.getElementById('btn-close-rf-modal')?.addEventListener('click', closeRaceFormModal);
  document.getElementById('btn-cancel-rf-modal')?.addEventListener('click', closeRaceFormModal);

  // Botones para modal de convocatoria rápida
  document.getElementById('btn-close-cq-modal')?.addEventListener('click', closeConvocatoriaModal);
  document.getElementById('btn-cancel-cq-modal')?.addEventListener('click', closeConvocatoriaModal);

  // Cargar dashboard por defecto
  loadDashboardData();
});

