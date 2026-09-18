/**
 * Intervals Fit Analytics - SPA Frontend Application Controller
 * Gestión de pestañas, peticiones REST, gráficos Chart.js y componentes dinámicos
 */

// Estado global de la aplicación
const AppState = {
  currentUser: null,
  athletes: [],
  currentTab: 'tab-dashboard',
  racesCalendar: [],
  raceFilter: 'all',
  peaksChart: null,
  loadEvolutionChart: null,
  loadTimeseriesData: [],
  peaksTableData: [],
  peaksTableView: 'compact',
  loadChartMetric: 'pmc',
  loadChartAthlete: 'team_avg',
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

  [AppState.peaksChart, AppState.loadEvolutionChart, AppState.mmpChart, AppState.raceHistoryChart].forEach(chart => {
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
  const role = AppState.currentUser ? AppState.currentUser.rol : 'visor';
  if (role === 'visor' && (tabId === 'tab-admin' || tabId === 'tab-users')) {
    tabId = 'tab-dashboard';
  } else if (role === 'editor' && tabId === 'tab-users') {
    tabId = 'tab-dashboard';
  }

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
    'tab-admin': 'Gestión de Ciclistas y Carreras',
    'tab-users': 'Gestión de Usuarios y Roles de Acceso'
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
    loadCacheStatus();
  }
  if (tabId === 'tab-users') {
    loadUsersAdminTable();
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

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function getAthleteDisplayName(athleteOrId) {
  if (!athleteOrId) return 'Ciclista';
  if (typeof athleteOrId === 'string') {
    const id = athleteOrId.trim();
    const found = (AppState.athletes || []).find(a => a.intervals_id === id || a.atleta_id === id);
    return (found && (found.name || found.nombre)) ? (found.name || found.nombre) : id;
  }
  const directName = athleteOrId.name || athleteOrId.nombre || athleteOrId.atleta_nombre;
  if (directName && directName !== athleteOrId.atleta_id && !/^i\d+$/i.test(directName)) {
    return directName;
  }
  const id = athleteOrId.atleta_id || athleteOrId.intervals_id;
  if (id) {
    const found = (AppState.athletes || []).find(a => a.intervals_id === id || a.atleta_id === id);
    if (found && (found.name || found.nombre)) {
      return found.name || found.nombre;
    }
  }
  return directName || athleteOrId.atleta_id || athleteOrId.intervals_id || 'Ciclista';
}

async function loadDashboardData() {
  try {
    const res = await fetch('/api/dashboard');
    if (!res.ok) throw new Error('Error al cargar dashboard');
    const data = await res.json();

    AppState.athletes = data.ciclistas || [];

    // Actualizar KPIs con comprobación defensiva
    const setElemText = (id, text) => {
      const el = document.getElementById(id);
      if (el) el.textContent = text;
    };

    setElemText('kpi-total-athletes', data.total_ciclistas);
    const activeCount = (data.carreras_activas && data.carreras_activas.length > 0)
      ? data.carreras_activas.reduce((acc, c) => acc + (c.num_convocados || (c.convocados ? c.convocados.length : 0)), 0)
      : 0;
    setElemText('kpi-active-racers', `${activeCount} activos en carrera`);

    setElemText('kpi-total-activities', data.db_stats?.num_actividades || 0);
    const racesCount = data.total_carreras ?? data.db_stats?.num_carreras ?? 0;
    setElemText('kpi-races-count', `${racesCount} carreras registradas`);

    const totalKj = data.db_stats?.total_kj_registrados || 0;
    setElemText('kpi-total-work', `${(totalKj).toLocaleString()} kJ`);

    setElemText('kpi-total-peaks', data.db_stats?.num_picos_registrados || 0);
    setElemText('sidebar-db-size', `${data.db_stats?.tamano_kb || 0} KB`);

    // Renderizar Bloques de Carreras en Vivo o Próximas en Dashboard
    renderDashboardRaces(data.carreras_activas, data.proxima_carrera, data.ultima_carrera);

    // Cargar carreras para selectores de informe de potencia
    loadRacesForSelects();

    // Últimas etapas registradas (si el contenedor está presente en el DOM)
    const tbodyStages = document.getElementById('tbody-recent-stages');
    if (tbodyStages) {
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

  const role = AppState.currentUser ? AppState.currentUser.rol : 'visor';
  const isVisor = role === 'visor';

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
        ? convocados.map(a => {
            const displayName = getAthleteDisplayName(a);
            const badgeMeta = a.rol || (a.dorsal ? `Dorsal #${a.dorsal}` : '');
            const foundAth = (AppState.athletes || []).find(ath => (ath.intervals_id && ath.intervals_id === a.atleta_id) || (ath.atleta_id && ath.atleta_id === a.atleta_id));
            const weightVal = a.weight || a.peso || (foundAth ? (foundAth.weight || foundAth.peso) : null);
            const ftpVal = a.ftp || (foundAth ? (foundAth.ftp || foundAth.FTP) : null);
            const statsSub = (weightVal && ftpVal) ? `(${weightVal} kg, ${ftpVal} W)` : (weightVal ? `(${weightVal} kg)` : '');
            return `
            <li class="race-roster-item">
              <div>
                <strong>${escapeHtml(displayName)}</strong>
                <!--${statsSub ? `<span style="font-size: 0.8rem; color: var(--text-dim);">${escapeHtml(statsSub)}</span>` : ''}-->
              </div>
              <!--${badgeMeta ? `<span class="mono" style="font-size: 0.8rem; color: var(--text-muted);">${escapeHtml(badgeMeta)}</span>` : ''}-->
            </li>
          `;
          }).join('')
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
              ${!isVisor ? `
              <button class="btn btn-secondary btn-sm" style="padding: 2px 8px; font-size: 0.75rem;" onclick="openConvocatoriaModal('${c.carrera_id}')">
                👥 Modificar
              </button>
              ` : ''}
            </div>
            <ul class="race-roster-list">
              ${convocadosListHtml}
            </ul>
          </div>

          <div class="race-card-actions">
            <button class="btn btn-primary btn-sm" onclick="openRaceHistoryModal('${c.carrera_id}', '${escapeJs(c.nombre_carrera)}')">
              <span>📊</span> Histórico de la Vuelta
            </button>
            ${!isVisor ? `
            <button class="btn btn-secondary btn-sm" onclick="openEditRaceModal('${c.carrera_id}')">
              <span>✏️</span> Editar Carrera
            </button>
            ` : ''}
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
      ? convocados.map(a => `<span class="convocado-tag">${escapeHtml(getAthleteDisplayName(a))}</span>`).join('')
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
          ${!isVisor ? `
          <button class="btn btn-primary btn-sm" onclick="openConvocatoriaModal('${proximaCarrera.carrera_id}')">
            <span>👥</span> Gestionar Convocatoria
          </button>
          <button class="btn btn-secondary btn-sm" onclick="openEditRaceModal('${proximaCarrera.carrera_id}')">
            <span>✏️</span> Editar Carrera
          </button>
          ` : ''}
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
          ${!isVisor ? `
          <button class="btn btn-secondary btn-sm" onclick="openEditRaceModal('${ultimaCarrera.carrera_id}')">
            <span>✏️</span> Editar
          </button>
          ` : ''}
        </div>
      </div>
    `;
  }

  if (!cardsHtml) {
    container.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; color: var(--text-dim); padding: 36px 20px; background: var(--card-item-bg); border-radius: var(--radius-lg); border: 1px dashed var(--border-subtle);">
        <div style="font-size: 2.5rem; margin-bottom: 10px;">🏆</div>
        <h4 style="color: var(--text-main); margin-bottom: 8px;">No hay competiciones registradas en el calendario</h4>
        <p style="font-size: 0.88rem; color: var(--text-muted); max-width: 500px; margin: 0 auto 16px auto;">
          Da de alta las carreras de la temporada con sus fechas de inicio, fin y ciclistas convocados para habilitar el seguimiento automático en vivo.
        </p>
        ${!isVisor ? `
        <button class="btn btn-primary" onclick="openCreateRaceModal()">
          <span>➕</span> Dar de Alta Primera Carrera
        </button>
        ` : ''}
      </div>
    `;
    return;
  }

  container.innerHTML = cardsHtml;
}

function updateReportRaceSelect(races) {
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

  sel.innerHTML = html;
  if (currentVal) sel.value = currentVal;
}

function updateStageRaceSelect(races) {
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

  html += `<option value="todos">Todos los corredores (Sin filtro)</option>`;

  sel.innerHTML = html;
  if (currentVal) sel.value = currentVal;
}

async function loadRacesForSelects() {
  try {
    const res = await fetch('/api/races');
    if (res.ok) {
      AppState.racesCalendar = await res.json();
    }
  } catch (e) {
    // Silencioso
  }
  updateReportRaceSelect(AppState.racesCalendar);
  updateStageRaceSelect(AppState.racesCalendar);
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

// Sincronización en segundo plano con Intervals.icu (solo actividades nuevas)
document.getElementById('btn-sync-api')?.addEventListener('click', async () => {
  if (AppState.isSyncing) {
    showToast('Ya hay una sincronización en curso', 'info');
    return;
  }
  try {
    AppState.isSyncing = true;
    const apiStatusEl = document.getElementById('api-status-text');
    if (apiStatusEl) apiStatusEl.textContent = 'Sincronizando actividades nuevas...';
    showToast('Iniciando sincronización de actividades nuevas...', 'info');

    const res = await fetch('/api/sync?solo_nuevas=true', { method: 'POST' });
    const data = await res.json();
    showToast(data.message, 'info');

    // Poll status cada 3 segundos
    const pollInterval = setInterval(async () => {
      const sRes = await fetch('/api/sync/status');
      const sData = await sRes.json();
      if (!sData.running) {
        clearInterval(pollInterval);
        AppState.isSyncing = false;
        if (apiStatusEl) apiStatusEl.textContent = 'Conectado a Intervals.icu';
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

const SQUAD_COLORS = [
  '#0284c7', // Sky blue
  '#059669', // Emerald
  '#d97706', // Amber
  '#e11d48', // Rose
  '#7c3aed', // Purple
  '#0d9488', // Teal
  '#ea580c', // Orange
  '#4f46e5', // Indigo
  '#db2777', // Pink
  '#16a34a', // Green
  '#0891b2', // Cyan
  '#9333ea', // Fuchsia
  '#ca8a04', // Yellow
  '#64748b'  // Slate
];

const PEAK_DURATIONS_LIST = [
  { key: '5s', label: '5s (Sprint)' },
  { key: '30s', label: '30s (Sprint L.)' },
  { key: '1m', label: '1m (Anaerób.)' },
  { key: '5m', label: '5m (VO2máx)' },
  { key: '10m', label: '10m (Ataque)' },
  { key: '20m', label: '20m (FTP / Umbral)' }
];

function renderPeakCell(durData) {
  if (!durData) return `<span class="mono" style="color: var(--text-dim);">-</span>`;

  const peakW = durData.peak_watts;
  const peakWkg = durData.peak_wkg;
  const histW = durData.all_time_watts;
  const histWkg = durData.all_time_wkg;
  const pctPr = durData.pct_pr;
  const esPr = durData.es_pr;

  if (peakW !== null && peakW !== undefined) {
    let badgeHtml = '';
    let valClass = 'peak-cell-val';

    if (esPr) {
      valClass += ' is-pr';
      badgeHtml = `<span class="badge badge-pr">🏆 PR</span>`;
    } else if (pctPr !== null && pctPr !== undefined) {
      if (pctPr >= 95) {
        badgeHtml = `<span class="badge badge-pr-near">🔥 ${pctPr}%</span>`;
      } else if (pctPr >= 85) {
        badgeHtml = `<span class="badge badge-pr-mid">⚡ ${pctPr}%</span>`;
      } else {
        badgeHtml = `<span class="badge badge-pr-sub">${pctPr}%</span>`;
      }
    }

    const prLabel = (histW && !esPr) ? `<span class="peak-cell-record" title="Récord Histórico PR">PR: ${histW}W (${histWkg ? `${histWkg} W/kg` : '-'})</span>` : '';

    return `
      <div class="peak-cell">
        <div class="peak-cell-main">
          <span class="${valClass}">${peakW} W</span>
          <span class="peak-cell-wkg">${peakWkg ? `${peakWkg} W/kg` : ''}</span>
        </div>
        <div class="peak-cell-sub">
          ${prLabel}
          ${badgeHtml}
        </div>
      </div>
    `;
  } else if (histW !== null && histW !== undefined) {
    return `
      <div class="peak-cell">
        <div class="peak-cell-main">
          <span class="peak-cell-val" style="color: var(--text-dim); font-size: 0.85rem;">--</span>
        </div>
        <div class="peak-cell-sub">
          <span class="peak-cell-record" style="color: var(--text-muted);">PR: ${histW} W (${histWkg ? `${histWkg} W/kg` : '-'})</span>
        </div>
      </div>
    `;
  }

  return `<span class="mono" style="color: var(--text-dim);">-</span>`;
}

function renderPeaksTable(peaksData) {
  const thead = document.getElementById('thead-peaks-report');
  const tbody = document.getElementById('tbody-peaks-report');
  if (!thead || !tbody) return;

  if (!peaksData || !peaksData.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-dim);">No se encontraron picos recientes para los ciclistas del grupo.</td></tr>`;
    return;
  }

  const isSplit = (AppState.peaksTableView === 'split');

  if (isSplit) {
    thead.innerHTML = `
      <tr>
        <th rowspan="2" style="min-width: 160px; vertical-align: middle;">Ciclista</th>
        ${PEAK_DURATIONS_LIST.map(d => `<th colspan="2" style="text-align: center; border-left: 1px solid var(--border-medium);">${d.label}</th>`).join('')}
      </tr>
      <tr>
        ${PEAK_DURATIONS_LIST.map(() => `
          <th style="font-size: 0.72rem; padding: 6px 8px; border-left: 1px solid var(--border-medium);">Reciente</th>
          <th style="font-size: 0.72rem; padding: 6px 8px;">Récord PR</th>
        `).join('')}
      </tr>
    `;

    tbody.innerHTML = peaksData.map(r => {
      const durs = r.duraciones || {};
      const cells = PEAK_DURATIONS_LIST.map(d => {
        const item = durs[d.key];
        const peakW = item?.peak_watts;
        const peakWkg = item?.peak_wkg;
        const histW = item?.all_time_watts;
        const histWkg = item?.all_time_wkg;
        const pctPr = item?.pct_pr;
        const esPr = item?.es_pr;

        let badge = '';
        if (esPr) {
          badge = `<span class="badge badge-pr" style="margin-left: 4px; font-size: 0.68rem;">🏆</span>`;
        } else if (pctPr >= 95) {
          badge = `<span class="badge badge-pr-near" style="margin-left: 4px; font-size: 0.68rem;">${pctPr}%</span>`;
        } else if (pctPr >= 85) {
          badge = `<span class="badge badge-pr-mid" style="margin-left: 4px; font-size: 0.68rem;">${pctPr}%</span>`;
        } else if (pctPr) {
          badge = `<span class="badge badge-pr-sub" style="margin-left: 4px; font-size: 0.68rem;">${pctPr}%</span>`;
        }

        const recHtml = peakW !== null && peakW !== undefined
          ? `<span class="mono" style="font-weight: 600;">${peakW} W</span> <span class="mono" style="font-size: 0.78rem; color: var(--accent-cyan);">${peakWkg ? `${peakWkg}` : ''}</span>`
          : `<span class="mono" style="color: var(--text-dim);">--</span>`;

        const histHtml = histW !== null && histW !== undefined
          ? `<span class="mono" style="color: var(--text-muted);">${histW} W</span> <span class="mono" style="font-size: 0.76rem; color: var(--text-dim);">${histWkg ? `(${histWkg})` : ''}</span> ${badge}`
          : `<span class="mono" style="color: var(--text-dim);">-</span>`;

        return `
          <td style="border-left: 1px solid var(--border-subtle); padding: 10px 8px;">${recHtml}</td>
          <td style="padding: 10px 8px;">${histHtml}</td>
        `;
      }).join('');

      return `
        <tr>
          <td><strong style="color: var(--text-bright);">${r['Ciclista'] || r['Name'] || 'Atleta'}</strong></td>
          ${cells}
        </tr>
      `;
    }).join('');

  } else {
    thead.innerHTML = `
      <tr>
        <th style="min-width: 160px;">Ciclista</th>
        ${PEAK_DURATIONS_LIST.map(d => `<th>${d.label}</th>`).join('')}
      </tr>
    `;

    tbody.innerHTML = peaksData.map(r => {
      const durs = r.duraciones || {};
      return `
        <tr>
          <td><strong style="color: var(--text-bright); font-size: 0.92rem;">${r['Ciclista'] || r['Name'] || 'Atleta'}</strong></td>
          ${PEAK_DURATIONS_LIST.map(d => `<td>${renderPeakCell(durs[d.key])}</td>`).join('')}
        </tr>
      `;
    }).join('');
  }
}

function initPeaksTableControls() {
  const btnCompact = document.getElementById('btn-peaks-view-compact');
  const btnSplit = document.getElementById('btn-peaks-view-split');

  if (btnCompact && !btnCompact._bound) {
    btnCompact._bound = true;
    btnCompact.addEventListener('click', () => {
      btnCompact.classList.add('active');
      btnCompact.classList.remove('btn-secondary');
      btnSplit?.classList.remove('active');
      btnSplit?.classList.add('btn-secondary');
      AppState.peaksTableView = 'compact';
      renderPeaksTable(AppState.peaksTableData);
    });
  }

  if (btnSplit && !btnSplit._bound) {
    btnSplit._bound = true;
    btnSplit.addEventListener('click', () => {
      btnSplit.classList.add('active');
      btnSplit.classList.remove('btn-secondary');
      btnCompact?.classList.remove('active');
      btnCompact?.classList.add('btn-secondary');
      AppState.peaksTableView = 'split';
      renderPeaksTable(AppState.peaksTableData);
    });
  }
}

async function loadPowerReport() {
  const grupoVal = document.getElementById('report-select-group')?.value;
  const dias = document.getElementById('report-select-days-peaks')?.value || 30;
  const diasCarga = document.getElementById('report-select-days-load')?.value || 60;

  const tbodyPeaks = document.getElementById('tbody-peaks-report');
  const tbodyLoad = document.getElementById('tbody-load-report');
  if (tbodyPeaks) tbodyPeaks.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-dim);">Consultando picos y evolución en Intervals.icu...</td></tr>`;

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

    // 1. Tabla de Picos comparada con Récord Histórico PR (6 duraciones)
    AppState.peaksTableData = data.peaks_table || [];
    initPeaksTableControls();
    renderPeaksTable(AppState.peaksTableData);

    if (data.peaks_table && data.peaks_table.length > 0) {
      renderPeaksChart(data.peaks_table);
    }

    // 2. Gráfico de Evolución de Carga (CTL / ATL / TSB)
    AppState.loadTimeseriesData = data.load_timeseries || [];
    initLoadChartControls(data.load_timeseries || []);
    renderLoadEvolutionChart();

    // 3. Tabla de Carga y Bienestar
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

function initLoadChartControls(timeseries) {
  const selectAthlete = document.getElementById('load-chart-athlete-select');
  if (selectAthlete) {
    const currentSelected = AppState.loadChartAthlete || 'team_avg';
    const realAthletes = timeseries.filter(a => !a.is_team_avg);

    selectAthlete.innerHTML = `
      <option value="team_avg" ${currentSelected === 'team_avg' ? 'selected' : ''}>⭐ Media del Equipo (PMC)</option>
      <option value="__all__" ${currentSelected === '__all__' ? 'selected' : ''}>👥 Comparativa (Todos los Ciclistas)</option>
      ${realAthletes.map(a => `<option value="${a.athlete_name}" ${a.athlete_name === currentSelected ? 'selected' : ''}>👤 ${a.athlete_name}</option>`).join('')}
    `;
  }

  // Listener para el selector de corredor
  if (selectAthlete && !selectAthlete._bound) {
    selectAthlete._bound = true;
    selectAthlete.addEventListener('change', (e) => {
      AppState.loadChartAthlete = e.target.value;
      renderLoadEvolutionChart();
    });
  }

  // Listeners para los botones de métrica (PMC / CTL / ATL / TSB / BOTH)
  const metricButtons = document.querySelectorAll('#load-chart-metric-buttons button');
  metricButtons.forEach(btn => {
    if (!btn._bound) {
      btn._bound = true;
      btn.addEventListener('click', () => {
        metricButtons.forEach(b => {
          b.classList.remove('active');
          b.classList.add('btn-secondary');
        });
        btn.classList.add('active');
        btn.classList.remove('btn-secondary');
        AppState.loadChartMetric = btn.getAttribute('data-metric') || 'pmc';
        renderLoadEvolutionChart();
      });
    }
  });
}

function renderPeaksChart(peaksData) {
  const ctx = document.getElementById('chart-peaks-comparison');
  if (!ctx) return;

  if (AppState.peaksChart) {
    AppState.peaksChart.destroy();
  }

  const labels = peaksData.map(d => d['Ciclista'] || d['Name'] || 'Atleta');
  const data5mReciente = peaksData.map(d => (d.duraciones && d.duraciones['5m']) ? (d.duraciones['5m'].peak_wkg || 0) : (parseFloat(d['5m (W/kg)']) || 0));
  const data5mRecord = peaksData.map(d => (d.duraciones && d.duraciones['5m']) ? (d.duraciones['5m'].all_time_wkg || 0) : (parseFloat(d['5m PR (W/kg)']) || 0));
  const data20mReciente = peaksData.map(d => (d.duraciones && d.duraciones['20m']) ? (d.duraciones['20m'].peak_wkg || 0) : (parseFloat(d['20m (W/kg)']) || 0));
  const data20mRecord = peaksData.map(d => (d.duraciones && d.duraciones['20m']) ? (d.duraciones['20m'].all_time_wkg || 0) : (parseFloat(d['20m PR (W/kg)']) || 0));

  const textColor = getChartTextColor();
  const gridColor = getChartGridColor();

  AppState.peaksChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {
          label: '5m Reciente (W/kg)',
          data: data5mReciente,
          backgroundColor: 'rgba(2, 132, 199, 0.85)',
          borderColor: '#0284c7',
          borderWidth: 1,
          borderRadius: 5
        },
        {
          label: '5m Récord PR (W/kg)',
          data: data5mRecord,
          backgroundColor: 'rgba(217, 119, 6, 0.35)',
          borderColor: '#d97706',
          borderWidth: 1.5,
          borderDash: [4, 4],
          borderRadius: 5
        },
        {
          label: '20m Reciente (W/kg)',
          data: data20mReciente,
          backgroundColor: 'rgba(5, 150, 105, 0.85)',
          borderColor: '#059669',
          borderWidth: 1,
          borderRadius: 5
        },
        {
          label: '20m Récord PR (W/kg)',
          data: data20mRecord,
          backgroundColor: 'rgba(16, 185, 129, 0.35)',
          borderColor: '#10b981',
          borderWidth: 1.5,
          borderDash: [4, 4],
          borderRadius: 5
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: textColor, boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              return ` ${ctx.dataset.label}: ${ctx.raw} W/kg`;
            }
          }
        }
      },
      scales: {
        x: { ticks: { color: textColor }, grid: { color: gridColor } },
        y: { 
          title: { display: true, text: 'W/kg', color: textColor },
          ticks: { color: textColor }, 
          grid: { color: gridColor },
          suggestedMin: 3.0
        }
      }
    }
  });
}

function renderLoadEvolutionChart() {
  const ctx = document.getElementById('chart-load-evolution');
  if (!ctx) return;

  if (AppState.loadEvolutionChart) {
    AppState.loadEvolutionChart.destroy();
    AppState.loadEvolutionChart = null;
  }

  const timeseries = AppState.loadTimeseriesData || [];
  if (!timeseries.length) {
    return;
  }

  const textColor = getChartTextColor();
  const gridColor = getChartGridColor();
  const selectedAthlete = AppState.loadChartAthlete || 'team_avg';
  const selectedMetric = AppState.loadChartMetric || 'pmc';

  // Extraer lista ordenada de fechas únicas
  const allDatesSet = new Set();
  timeseries.forEach(ath => {
    (ath.series || []).forEach(pt => {
      if (pt.fecha) allDatesSet.add(pt.fecha);
    });
  });
  const labels = Array.from(allDatesSet).sort();

  const formatTickDate = function(val, index) {
    const s = String(labels[index] ?? labels[val] ?? '');
    return s.length >= 10 ? s.slice(5) : s;
  };

  const subtitle = document.getElementById('load-chart-subtitle');

  if (selectedMetric === 'pmc' || (selectedAthlete !== '__all__' && selectedMetric === 'both')) {
    // MODO PMC COMPLETO: CTL (Fitness) + ATL (Fatiga) + TSB (Forma) + TSS diario
    let targetSeries = null;
    let targetName = '';

    if (selectedAthlete === 'team_avg') {
      targetSeries = timeseries.find(a => a.is_team_avg) || timeseries[0];
      targetName = 'Media del Equipo';
    } else if (selectedAthlete === '__all__') {
      targetSeries = timeseries.find(a => a.is_team_avg) || timeseries[0];
      targetName = 'Media del Equipo';
    } else {
      targetSeries = timeseries.find(a => a.athlete_name === selectedAthlete);
      targetName = selectedAthlete;
    }

    if (!targetSeries) return;

    const dateMap = {};
    (targetSeries.series || []).forEach(pt => {
      dateMap[pt.fecha] = pt;
    });

    const dataCtl = labels.map(d => dateMap[d]?.ctl ?? null);
    const dataAtl = labels.map(d => dateMap[d]?.atl ?? null);
    const dataTsb = labels.map(d => dateMap[d]?.tsb ?? null);
    const dataTss = labels.map(d => dateMap[d]?.daily_load ?? 0);

    const lastPt = (targetSeries.series && targetSeries.series.length) ? targetSeries.series[targetSeries.series.length - 1] : {};
    if (subtitle) {
      subtitle.innerHTML = `<strong>${targetName}</strong> — CTL (Fitness): <span style="color: var(--accent-cyan); font-weight:700;">${lastPt.ctl ?? '-'}</span> | ATL (Fatiga): <span style="color: var(--accent-rose); font-weight:700;">${lastPt.atl ?? '-'}</span> | TSB (Forma): <span style="color: ${parseFloat(lastPt.tsb) >= 0 ? 'var(--accent-emerald)' : 'var(--accent-amber)'}; font-weight:700;">${lastPt.tsb ?? '-'}</span>`;
    }

    AppState.loadEvolutionChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          {
            type: 'bar',
            label: 'TSS Diario (Carga)',
            data: dataTss,
            backgroundColor: 'rgba(148, 163, 184, 0.25)',
            borderColor: 'rgba(148, 163, 184, 0.4)',
            borderWidth: 1,
            borderRadius: 3,
            yAxisID: 'yTss',
            order: 4
          },
          {
            type: 'line',
            label: 'CTL (Fitness acumulado)',
            data: dataCtl,
            borderColor: '#0284c7',
            backgroundColor: 'rgba(2, 132, 199, 0.08)',
            borderWidth: 3.0,
            pointRadius: 1.5,
            pointHoverRadius: 6,
            tension: 0.25,
            yAxisID: 'yPmc',
            order: 1,
            spanGaps: true
          },
          {
            type: 'line',
            label: 'ATL (Fatiga aguda)',
            data: dataAtl,
            borderColor: '#f43f5e',
            borderWidth: 2.4,
            borderDash: [5, 3],
            pointRadius: 1.5,
            pointHoverRadius: 6,
            tension: 0.25,
            yAxisID: 'yPmc',
            order: 2,
            spanGaps: true
          },
          {
            type: 'line',
            label: 'TSB (Forma / Balance)',
            data: dataTsb,
            borderColor: '#10b981',
            borderWidth: 2.0,
            pointRadius: 1.5,
            pointHoverRadius: 6,
            tension: 0.25,
            yAxisID: 'yPmc',
            order: 3,
            spanGaps: true
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top', labels: { color: textColor, boxWidth: 14 } },
          tooltip: {
            callbacks: {
              label: function(c) {
                const val = c.raw !== null ? c.raw : '-';
                return ` ${c.dataset.label}: ${val}`;
              }
            }
          }
        },
        scales: {
          x: {
            ticks: { color: textColor, maxTicksLimit: 14, callback: formatTickDate },
            grid: { color: gridColor }
          },
          yPmc: {
            position: 'left',
            title: { display: true, text: 'CTL / ATL / TSB', color: textColor },
            ticks: { color: textColor },
            grid: { color: gridColor }
          },
          yTss: {
            position: 'right',
            title: { display: true, text: 'TSS', color: textColor },
            ticks: { color: textColor },
            grid: { display: false },
            suggestedMax: 200,
            min: 0
          }
        }
      }
    });

  } else if (selectedMetric === 'both') {
    // MODO SIMULTÁNEO: CTL (línea continua) y ATL (línea discontinua) para todos los ciclistas
    const realAthletes = timeseries.filter(a => !a.is_team_avg);
    const datasets = [];

    realAthletes.forEach((ath, idx) => {
      const color = SQUAD_COLORS[idx % SQUAD_COLORS.length];
      const dateMap = {};
      (ath.series || []).forEach(pt => { dateMap[pt.fecha] = pt; });

      datasets.push({
        label: `${ath.athlete_name} (CTL)`,
        data: labels.map(d => dateMap[d]?.ctl ?? null),
        borderColor: color,
        backgroundColor: color,
        fill: false,
        tension: 0.25,
        borderWidth: 2.4,
        pointRadius: 1.5,
        pointHoverRadius: 5,
        spanGaps: true
      });

      datasets.push({
        label: `${ath.athlete_name} (ATL)`,
        data: labels.map(d => dateMap[d]?.atl ?? null),
        borderColor: color,
        borderDash: [5, 4],
        backgroundColor: color,
        fill: false,
        tension: 0.25,
        borderWidth: 1.8,
        pointRadius: 1,
        pointHoverRadius: 5,
        spanGaps: true
      });
    });

    if (subtitle) {
      subtitle.textContent = `Comparativa simultánea de CTL (línea continua) y ATL (línea punteada) de todos los ciclistas.`;
    }

    AppState.loadEvolutionChart = new Chart(ctx, {
      type: 'line',
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top', labels: { color: textColor, boxWidth: 12 } },
          tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${c.raw !== null ? c.raw : '-'}` } }
        },
        scales: {
          x: { ticks: { color: textColor, maxTicksLimit: 14, callback: formatTickDate }, grid: { color: gridColor } },
          y: { title: { display: true, text: 'Carga (CTL / ATL)', color: textColor }, ticks: { color: textColor }, grid: { color: gridColor } }
        }
      }
    });

  } else {
    // MODO MÉTRICA ÚNICA: CTL, ATL o TSB entre todos los ciclistas
    const metricLabels = {
      ctl: 'CTL (Fitness acumulado)',
      atl: 'ATL (Fatiga aguda)',
      tsb: 'TSB (Balance de Forma)'
    };
    const metricUnit = metricLabels[selectedMetric] || selectedMetric.toUpperCase();
    const realAthletes = timeseries.filter(a => !a.is_team_avg);

    const datasets = realAthletes.map((ath, idx) => {
      const color = SQUAD_COLORS[idx % SQUAD_COLORS.length];
      const dateMap = {};
      (ath.series || []).forEach(pt => { dateMap[pt.fecha] = pt[selectedMetric]; });

      return {
        label: ath.athlete_name,
        data: labels.map(d => (dateMap[d] !== undefined ? dateMap[d] : null)),
        borderColor: color,
        backgroundColor: color,
        fill: false,
        tension: 0.25,
        borderWidth: 2.2,
        pointRadius: 1.5,
        pointHoverRadius: 6,
        spanGaps: true
      };
    });

    if (subtitle) {
      subtitle.textContent = `Comparativa de ${metricUnit} entre los ciclistas convocados.`;
    }

    AppState.loadEvolutionChart = new Chart(ctx, {
      type: 'line',
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top', labels: { color: textColor, boxWidth: 12 } },
          tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${c.raw !== null ? c.raw : '-'}` } }
        },
        scales: {
          x: { ticks: { color: textColor, maxTicksLimit: 14, callback: formatTickDate }, grid: { color: gridColor } },
          y: { title: { display: true, text: metricUnit, color: textColor }, ticks: { color: textColor }, grid: { color: gridColor } }
        }
      }
    });
  }
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

    const role = AppState.currentUser ? AppState.currentUser.rol : 'visor';
    const isVisor = role === 'visor';
    const isAdmin = role === 'administrador';

    tbody.innerHTML = athletes.map(a => `
      <tr>
        <td><strong>${escapeHtml(a.name)}</strong></td>
        <td class="mono">${escapeHtml(a.intervals_id)}</td>
        <td class="mono">${a.weight} kg</td>
        <td class="mono">${a.ftp} W</td>
        <td class="mono">${a.biela} mm</td>
        <td>
          ${isVisor ? '<span style="font-size: 0.78rem; color: var(--text-dim);">Solo lectura</span>' : `
            <button class="btn btn-secondary btn-sm" onclick="openEditAthleteModal('${escapeJs(a.intervals_id)}')">✏️ Editar</button>
            ${isAdmin ? `<button class="btn btn-danger btn-sm" onclick="deleteAthletePrompt('${escapeJs(a.intervals_id)}', '${escapeJs(a.name)}')">🗑️</button>` : ''}
          `}
        </td>
      </tr>
    `).join('');

    // Convocatoria checklist
    if (checklistContainer) {
      checklistContainer.innerHTML = athletes.map(a => `
        <label style="background: var(--checklist-item-bg); padding: 10px 14px; border-radius: var(--radius-md); border: 1px solid var(--border-subtle); display: flex; align-items: center; gap: 10px; cursor: pointer;">
          <input type="checkbox" value="${a.intervals_id}" class="chk-assign-athlete" style="accent-color: var(--accent-cyan);">
          <div>
            <div style="font-weight: 600; font-size: 0.9rem;">${a.name}</div>
            <div style="font-size: 0.75rem; color: var(--text-dim);">${a.intervals_id}</div>
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

  const role = AppState.currentUser ? AppState.currentUser.rol : 'visor';
  const isVisor = role === 'visor';
  const isAdmin = role === 'administrador';

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
        visible.map(c => `<span class="convocado-tag">${escapeHtml(getAthleteDisplayName(c))}</span>`).join('') +
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
            ${!isVisor ? `
              <button class="btn btn-secondary btn-sm" style="padding: 3px 8px; font-size: 0.78rem;" onclick="openConvocatoriaModal('${r.carrera_id}')" title="Ajustar convocatoria">
                <span>👥</span> Convocatoria
              </button>
            ` : ''}
            <button class="btn btn-secondary btn-sm" style="padding: 3px 8px; font-size: 0.78rem;" onclick="openRaceHistoryModal('${r.carrera_id}', '${escapeJs(r.nombre_carrera)}')" title="Ver histórico">
              <span>📊</span> Histórico
            </button>
            ${!isVisor ? `
              <button class="btn btn-secondary btn-sm" style="padding: 3px 8px; font-size: 0.78rem;" onclick="openEditRaceModal('${r.carrera_id}')" title="Editar datos">
                <span>✏️</span>
              </button>
            ` : ''}
            ${isAdmin ? `
              <button class="btn btn-danger btn-sm" style="padding: 3px 8px; font-size: 0.78rem;" onclick="deleteRacePrompt('${r.carrera_id}', '${escapeJs(r.nombre_carrera)}')" title="Eliminar carrera">
                <span>🗑️</span>
              </button>
            ` : ''}
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
    biela: parseFloat(document.getElementById('form-athlete-biela').value)
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

    if (!resStages.ok) {
      const errStages = await resStages.json().catch(() => ({}));
      throw new Error(errStages.detail || 'Error al cargar etapas históricas');
    }
    if (!resSummary.ok) {
      const errSum = await resSummary.json().catch(() => ({}));
      throw new Error(errSum.detail || 'Error al cargar balance de la vuelta');
    }

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
// MÓDULO 6: AUTENTICACIÓN, SESIONES Y CONTROL DE ACCESO (RBAC)
// =============================================================================

// Interceptor global para redirección automática a /login si expira la sesión (401)
const _origFetch = window.fetch;
window.fetch = async function(...args) {
  const response = await _origFetch(...args);
  if (response.status === 401 && !window.location.pathname.startsWith('/login')) {
    window.location.href = '/login';
  }
  return response;
};

async function initAuthAndUser() {
  try {
    const res = await fetch('/api/auth/me');
    if (!res.ok) {
      window.location.href = '/login';
      return false;
    }
    const user = await res.json();
    AppState.currentUser = user;

    updateUserUI(user);
    applyRoleRestrictions(user.rol);
    return true;
  } catch (e) {
    window.location.href = '/login';
    return false;
  }
}

function updateUserUI(user) {
  if (!user) return;
  const unameEl = document.getElementById('topbar-username');
  const roleEl = document.getElementById('topbar-user-role');
  const avatarEl = document.getElementById('topbar-user-avatar');

  if (unameEl) unameEl.textContent = user.nombre_completo || user.username;
  if (roleEl) {
    if (user.rol === 'administrador') {
      roleEl.textContent = '👑 Administrador';
      roleEl.className = 'badge-role badge-role-admin';
      if (avatarEl) avatarEl.textContent = '👑';
    } else if (user.rol === 'editor') {
      roleEl.textContent = '✏️ Editor';
      roleEl.className = 'badge-role badge-role-editor';
      if (avatarEl) avatarEl.textContent = '✏️';
    } else {
      roleEl.textContent = '👁️ Visor';
      roleEl.className = 'badge-role badge-role-visor';
      if (avatarEl) avatarEl.textContent = '👁️';
    }
  }
}

function applyRoleRestrictions(role) {
  const visorBanner = document.getElementById('visor-notice-banner');
  const navAdmin = document.getElementById('nav-item-admin');
  const navUsers = document.getElementById('nav-item-users');
  const btnManageConvocatorias = document.getElementById('btn-manage-convocatorias');
  const btnSync = document.getElementById('btn-sync-api');
  const btnAddAthlete = document.getElementById('btn-open-add-athlete-modal');
  const btnCreateRace = document.getElementById('btn-open-create-race-modal');
  const btnAssignRace = document.getElementById('btn-assign-race');

  if (role === 'administrador') {
    if (visorBanner) visorBanner.style.display = 'none';
    if (navAdmin) navAdmin.style.display = '';
    if (navUsers) navUsers.style.display = 'block';
    if (btnManageConvocatorias) btnManageConvocatorias.style.display = 'inline-flex';
    if (btnSync) btnSync.style.display = 'inline-flex';
    if (btnAddAthlete) btnAddAthlete.style.display = 'inline-flex';
    if (btnCreateRace) btnCreateRace.style.display = 'inline-flex';
    if (btnAssignRace) btnAssignRace.style.display = 'inline-block';
  } else if (role === 'editor') {
    if (visorBanner) visorBanner.style.display = 'none';
    if (navAdmin) navAdmin.style.display = '';
    if (navUsers) navUsers.style.display = 'none';
    if (btnManageConvocatorias) btnManageConvocatorias.style.display = 'inline-flex';
    if (btnSync) btnSync.style.display = 'none';
    if (btnAddAthlete) btnAddAthlete.style.display = 'inline-flex';
    if (btnCreateRace) btnCreateRace.style.display = 'inline-flex';
    if (btnAssignRace) btnAssignRace.style.display = 'inline-block';
  } else {
    // Rol: visor (Solo Lectura) - Oculta la parte de gestión del equipo y administración
    if (visorBanner) visorBanner.style.display = 'flex';
    if (navAdmin) navAdmin.style.display = 'none';
    if (navUsers) navUsers.style.display = 'none';
    if (btnManageConvocatorias) btnManageConvocatorias.style.display = 'none';
    if (btnSync) btnSync.style.display = 'none';
    if (btnAddAthlete) btnAddAthlete.style.display = 'none';
    if (btnCreateRace) btnCreateRace.style.display = 'none';
    if (btnAssignRace) btnAssignRace.style.display = 'none';

    // Si el usuario estaba en tab-admin o tab-users, regresar a dashboard
    if (AppState.currentTab === 'tab-admin' || AppState.currentTab === 'tab-users') {
      navigateToTab('tab-dashboard');
    }
  }
}

async function handleLogout() {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
  } catch (e) {}
  localStorage.removeItem('ifa_token');
  localStorage.removeItem('ifa_user');
  window.location.href = '/login';
}

// -----------------------------------------------------------------------------
// GESTIÓN DE USUARIOS (CRUD PARA ADMINISTRADOR)
// -----------------------------------------------------------------------------

async function loadUsersAdminTable() {
  const tbody = document.getElementById('tbody-users-admin');
  if (!tbody) return;

  try {
    const res = await fetch('/api/users');
    if (!res.ok) {
      if (res.status === 401) {
        window.location.href = '/login';
        return;
      }
      throw new Error('Error al consultar usuarios');
    }
    const users = await res.json();

    if (users.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-dim); padding: 24px;">No hay usuarios registrados.</td></tr>';
      return;
    }

    tbody.innerHTML = users.map(u => {
      let roleBadge = '';
      if (u.rol === 'administrador') {
        roleBadge = '<span class="badge-role-admin">👑 Administrador</span>';
      } else if (u.rol === 'editor') {
        roleBadge = '<span class="badge-role-editor">✏️ Editor</span>';
      } else {
        roleBadge = '<span class="badge-role-visor">👁️ Visor</span>';
      }

      const statusBadge = u.activo
        ? '<span class="badge-status-active">🟢 Activo</span>'
        : '<span class="badge-status-inactive">🔴 Inactivo</span>';

      const fechaAlta = u.creado_en ? u.creado_en.split(' ')[0] : '-';
      const ultimoAcceso = u.ultimo_acceso ? u.ultimo_acceso.replace('T', ' ').slice(0, 16) : 'Nunca';

      const isSelf = AppState.currentUser && AppState.currentUser.username.toLowerCase() === u.username.toLowerCase();

      return `
        <tr>
          <td><strong class="mono">${escapeHtml(u.username)}</strong> ${isSelf ? '<span style="font-size: 0.72rem; color: var(--accent-cyan);">(Tú)</span>' : ''}</td>
          <td>${escapeHtml(u.nombre_completo || '-')}</td>
          <td>${roleBadge}</td>
          <td>${statusBadge}</td>
          <td class="mono" style="font-size: 0.82rem;">${fechaAlta}</td>
          <td class="mono" style="font-size: 0.82rem; color: var(--text-dim);">${ultimoAcceso}</td>
          <td>
            <div class="user-table-actions">
              <button class="btn btn-secondary btn-sm btn-user-action" onclick="openChangePasswordModal('${escapeJs(u.username)}')" title="Cambiar contraseña">
                <span>🔑</span> Pass
              </button>
              <button class="btn btn-secondary btn-sm btn-user-action" onclick="openEditUserModal('${escapeJs(u.username)}', '${escapeJs(u.nombre_completo || '')}', '${escapeJs(u.rol)}', ${u.activo})" title="Editar usuario">
                <span>✏️</span> Rol
              </button>
              ${!isSelf ? `
                <button class="btn btn-danger btn-sm btn-user-action" onclick="deleteUserPrompt('${escapeJs(u.username)}')" title="Eliminar usuario">
                  <span>🗑️</span>
                </button>
              ` : ''}
            </div>
          </td>
        </tr>
      `;
    }).join('');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--accent-rose); padding: 20px;">Error al cargar la lista de usuarios.</td></tr>';
  }
}

function openCreateUserModal() {
  document.getElementById('form-create-user')?.reset();
  document.getElementById('modal-user-form')?.classList.add('active');
}

function closeCreateUserModal() {
  document.getElementById('modal-user-form')?.classList.remove('active');
}

async function handleCreateUserSubmit(e) {
  e.preventDefault();
  const username = document.getElementById('form-uf-username').value.trim();
  const nombre = document.getElementById('form-uf-nombre').value.trim();
  const rol = document.getElementById('form-uf-rol').value;
  const password = document.getElementById('form-uf-password').value;

  try {
    const res = await fetch('/api/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username,
        nombre_completo: nombre,
        rol,
        password
      })
    });

    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Usuario '${username}' creado con éxito`, 'success');
      closeCreateUserModal();
      loadUsersAdminTable();
    } else {
      showToast(data.detail || 'Error al crear el usuario', 'error');
    }
  } catch (err) {
    showToast('Error de conexión al crear usuario', 'error');
  }
}

function openEditUserModal(username, nombre, rol, activo) {
  document.getElementById('form-ue-username').value = username;
  document.getElementById('form-ue-nombre').value = nombre;
  document.getElementById('form-ue-rol').value = rol;
  document.getElementById('form-ue-activo').checked = Boolean(activo);
  const subEl = document.getElementById('modal-ue-subtitle');
  if (subEl) subEl.textContent = `Modificando cuenta de usuario: ${username}`;
  document.getElementById('modal-user-edit')?.classList.add('active');
}

function closeEditUserModal() {
  document.getElementById('modal-user-edit')?.classList.remove('active');
}

async function handleEditUserSubmit(e) {
  e.preventDefault();
  const username = document.getElementById('form-ue-username').value;
  const nombre = document.getElementById('form-ue-nombre').value.trim();
  const rol = document.getElementById('form-ue-rol').value;
  const activo = document.getElementById('form-ue-activo').checked;

  try {
    const res = await fetch(`/api/users/${encodeURIComponent(username)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        nombre_completo: nombre,
        rol,
        activo
      })
    });

    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Usuario '${username}' actualizado`, 'success');
      closeEditUserModal();
      loadUsersAdminTable();
      if (AppState.currentUser && AppState.currentUser.username.toLowerCase() === username.toLowerCase()) {
        AppState.currentUser.rol = rol;
        AppState.currentUser.nombre_completo = nombre;
        updateUserUI(AppState.currentUser);
      }
    } else {
      showToast(data.detail || 'Error al actualizar usuario', 'error');
    }
  } catch (err) {
    showToast('Error de conexión al actualizar usuario', 'error');
  }
}

function openChangePasswordModal(username) {
  document.getElementById('form-change-password')?.reset();
  document.getElementById('form-up-username').value = username;
  const subEl = document.getElementById('modal-up-subtitle');
  if (subEl) subEl.textContent = `Asignando nueva contraseña para: ${username}`;
  document.getElementById('modal-user-password')?.classList.add('active');
}

function closeChangePasswordModal() {
  document.getElementById('modal-user-password')?.classList.remove('active');
}

async function handleChangePasswordSubmit(e) {
  e.preventDefault();
  const username = document.getElementById('form-up-username').value;
  const newPwd = document.getElementById('form-up-new-pwd').value;
  const confirmPwd = document.getElementById('form-up-confirm-pwd').value;

  if (newPwd !== confirmPwd) {
    showToast('Las contraseñas ingresadas no coinciden', 'error');
    return;
  }

  try {
    const res = await fetch(`/api/users/${encodeURIComponent(username)}/password`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: newPwd })
    });

    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Contraseña actualizada para '${username}'`, 'success');
      closeChangePasswordModal();
    } else {
      showToast(data.detail || 'Error al actualizar contraseña', 'error');
    }
  } catch (err) {
    showToast('Error de conexión al actualizar contraseña', 'error');
  }
}

async function deleteUserPrompt(username) {
  if (!confirm(`¿Estás seguro de que deseas eliminar permanentemente la cuenta del usuario '${username}'?`)) {
    return;
  }

  try {
    const res = await fetch(`/api/users/${encodeURIComponent(username)}`, {
      method: 'DELETE'
    });

    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Usuario '${username}' eliminado`, 'success');
      loadUsersAdminTable();
    } else {
      showToast(data.detail || 'No se pudo eliminar el usuario', 'error');
    }
  } catch (err) {
    showToast('Error de conexión al eliminar usuario', 'error');
  }
}

// =============================================================================
// MÓDULO: GESTIÓN DE CACHÉ DE CÁLCULOS
// =============================================================================

async function loadCacheStatus() {
  try {
    const res = await fetch('/api/cache/status');
    if (!res.ok) return;
    const data = await res.json();

    // Telemetría FIT
    const catFits = data.categorias?.fits || {};
    setElemText('cache-stat-fits-count', catFits.num_archivos || 0);
    setElemText('cache-stat-fits-size', `${catFits.tamano_str || '0 B'} (today_race)`);

    // Clima
    const catWeather = data.categorias?.clima || {};
    setElemText('cache-stat-weather-count', catWeather.num_archivos || 0);
    setElemText('cache-stat-weather-size', `${catWeather.tamano_str || '0 B'} (Open-Meteo)`);

    // Picos y fatiga
    const catPeaks = data.categorias?.picos || {};
    setElemText('cache-stat-peaks-count', catPeaks.num_actividades || 0);
    setElemText('cache-stat-peaks-size', `${catPeaks.tamano_str || '0 B'} (histórico)`);

    // Total
    setElemText('cache-stat-total-size', data.total_tamano_str || '0 B');
    setElemText('cache-stat-total-files', `${data.total_archivos || 0} archivos temporales`);
  } catch (err) {
    console.warn('Error al cargar estado de la caché:', err);
  }
}

async function handleClearCache() {
  const confirmMsg = '¿Deseas vaciar todos los archivos de caché generados durante los cálculos?\n\n' +
    '• Se eliminarán los archivos FIT temporales locales (today_race).\n' +
    '• Se eliminarán las consultas meteorológicas en caché (weather_cache).\n' +
    '• Se reseteará la caché de picos históricos y fatiga previa (kJ).\n\n' +
    'Nota: La base de datos histórica y la lista de ciclistas NO se verán afectadas.';

  if (!confirm(confirmMsg)) return;

  const btn = document.getElementById('btn-clear-cache');
  const originalText = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span> Limpiando...';
  }

  try {
    showToast('Limpiando archivos de caché de cálculo...', 'info');
    const res = await fetch('/api/cache/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        limpiar_fits: true,
        limpiar_clima: true,
        limpiar_picos: true,
        limpiar_scratch: true
      })
    });

    const data = await res.json();
    if (res.ok) {
      showToast(data.mensaje || 'Caché eliminada con éxito', 'success');
      await loadCacheStatus();
    } else {
      showToast(data.detail || 'Error al vaciar la caché', 'error');
    }
  } catch (err) {
    showToast('Error de conexión al vaciar la caché', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }
}

// =============================================================================
// INICIALIZACIÓN AL CARGAR LA PÁGINA
// =============================================================================

document.addEventListener('DOMContentLoaded', async () => {
  // Inicializar controlador de tema
  initTheme();

  // Configurar listeners de navegación
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      const tab = item.getAttribute('data-tab');
      navigateToTab(tab);
    });
  });

  // Configurar botón de logout
  document.getElementById('btn-logout')?.addEventListener('click', handleLogout);

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

  // Botones y formularios para modales de gestión de usuarios
  document.getElementById('btn-open-create-user-modal')?.addEventListener('click', openCreateUserModal);
  document.getElementById('btn-close-uf-modal')?.addEventListener('click', closeCreateUserModal);
  document.getElementById('btn-cancel-uf-modal')?.addEventListener('click', closeCreateUserModal);
  document.getElementById('form-create-user')?.addEventListener('submit', handleCreateUserSubmit);

  document.getElementById('btn-close-ue-modal')?.addEventListener('click', closeEditUserModal);
  document.getElementById('btn-cancel-ue-modal')?.addEventListener('click', closeEditUserModal);
  document.getElementById('form-edit-user')?.addEventListener('submit', handleEditUserSubmit);

  document.getElementById('btn-close-up-modal')?.addEventListener('click', closeChangePasswordModal);
  document.getElementById('btn-cancel-up-modal')?.addEventListener('click', closeChangePasswordModal);
  document.getElementById('form-change-password')?.addEventListener('submit', handleChangePasswordSubmit);

  // Botones de mantenimiento de caché de cálculos
  document.getElementById('btn-refresh-cache-status')?.addEventListener('click', () => {
    loadCacheStatus();
    showToast('Estado de caché actualizado', 'info', 2000);
  });
  document.getElementById('btn-clear-cache')?.addEventListener('click', handleClearCache);

  // 1. Verificar autenticación obligatoria y cargar perfil
  const authOk = await initAuthAndUser();
  if (!authOk) return;

  // 2. Cargar dashboard inicial
  loadDashboardData();
});

