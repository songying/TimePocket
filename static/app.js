'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const palette = [
    { bg: '#e8eddc', color: '#8da36b', icon: 'L' },
    { bg: '#f0e7d8', color: '#c3a26f', icon: 'P' },
    { bg: '#e8e5ef', color: '#a394b6', icon: 'E' },
    { bg: '#e3ecea', color: '#7caaa3', icon: 'R' },
    { bg: '#f0e5dd', color: '#c09b80', icon: 'W' },
    { bg: '#e6e9e0', color: '#93a18a', icon: '↺' },
  ];
  const statusNames = { pending: 'Scheduled', delivering: 'Sending', sent: 'Sent to Telegram', simulated: 'Simulated; no message sent', skipped: 'Skipped this time', expired: 'Expired', failed: 'Could not deliver', uncertain: 'Delivery unconfirmed' };
  let state = null;
  let mode = 'demo';
  let selectedWeek = '';
  let activeView = 'overview';
  let busy = false;
  let loadVersion = 0;
  let editingProject = null;
  let entryTimerId = null;
  let entryRequestId = null;
  let noticeTimeout;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function finite(value) { return Number.isFinite(Number(value)) ? Number(value) : 0; }
  function hours(value) { return finite(value).toLocaleString('en-US', { maximumFractionDigits: 2 }); }
  function projectById(id) { return state.projects.find((project) => String(project.id) === String(id)); }
  function projectColor(id) { return palette[Math.max(0, state.projects.findIndex((project) => String(project.id) === String(id))) % palette.length]; }
  function setProjectColor(node, id) {
    const color = projectColor(id);
    node.style.setProperty('--project-bg', color.bg);
    node.style.setProperty('--project-color', color.color);
    return color;
  }
  function iconFor(projectId) {
    const icon = element('span', 'project-icon');
    const color = setProjectColor(icon, projectId);
    icon.textContent = color.icon;
    icon.setAttribute('aria-hidden', 'true');
    return icon;
  }
  function dateParts(timestamp, timezone = state?.timezone || 'UTC') {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(timestamp * 1000));
    return Object.fromEntries(parts.filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]));
  }
  function localDate(timestamp) {
    const part = dateParts(timestamp);
    return `${part.year}-${part.month}-${part.day}`;
  }
  function localInput(timestamp) {
    const part = dateParts(timestamp);
    return `${part.year}-${part.month}-${part.day}T${part.hour}:${part.minute}`;
  }
  function inputToEpoch(value) {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) throw new Error('Choose a complete date and time.');
    const target = Date.parse(`${value}:00Z`) / 1000;
    let result = target;
    for (let count = 0; count < 5; count += 1) {
      const parts = dateParts(result);
      const represented = Date.parse(`${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}Z`) / 1000;
      const delta = target - represented;
      if (!delta) break;
      result += delta;
    }
    if (localInput(result) !== value) throw new Error('This time does not exist in your time zone, possibly due to daylight saving time. Choose another time.');
    return result;
  }
  function formattedDate(timestamp, options = {}) {
    return new Intl.DateTimeFormat('en-US', { timeZone: state.timezone, month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', ...options }).format(new Date(timestamp * 1000));
  }
  function shiftDate(value, days) {
    const date = new Date(`${value}T12:00:00Z`);
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
  }
  function currentWeek() {
    const today = localDate(Date.now() / 1000);
    const weekday = new Date(`${today}T12:00:00Z`).getUTCDay();
    return shiftDate(today, -(weekday === 0 ? 6 : weekday - 1));
  }
  function weekText(value) {
    const end = shiftDate(value, 6);
    const startParts = value.split('-');
    const endParts = end.split('-');
    return `${Number(startParts[1])}.${Number(startParts[2])} — ${Number(endParts[1])}.${Number(endParts[2])}`;
  }
  function showNotice(message, error = false) {
    clearTimeout(noticeTimeout);
    $('notice').textContent = message;
    $('notice').classList.toggle('error', error);
    $('notice').hidden = false;
    if (!error) noticeTimeout = setTimeout(() => { $('notice').hidden = true; }, 6500);
  }
  function clearErrors() {
    $('notice').hidden = true;
    document.querySelectorAll('.form-error').forEach((node) => { node.hidden = true; node.textContent = ''; });
  }
  function showError(error, form = null) {
    const message = error instanceof Error ? error.message : 'Unable to finish. Please try again shortly.';
    if (form) {
      const target = form.querySelector('.form-error');
      target.textContent = message;
      target.hidden = false;
    } else showNotice(message, true);
  }
  function syncBusy() {
    document.querySelectorAll('button, input, select, textarea').forEach((control) => {
      control.disabled = busy;
    });
    if (!busy && state?.timer) $('timer-project').disabled = true;
    document.body.setAttribute('aria-busy', String(busy));
  }
  async function api(path, payload) {
    const headers = {};
    if (mode === 'demo') headers['X-Demo-Mode'] = '1';
    else {
      const initData = window.Telegram?.WebApp?.initData;
      if (!initData) throw new Error('Open TimePocket from the Telegram bot to securely access your records.');
      headers.Authorization = `tma ${initData}`;
    }
    if (payload !== undefined) headers['Content-Type'] = 'application/json';
    let response;
    try {
      response = await fetch(path, { method: payload === undefined ? 'GET' : 'POST', headers, body: payload === undefined ? undefined : JSON.stringify(payload), credentials: 'same-origin' });
    } catch (_) { throw new Error('The connection was interrupted. Check your network and try again.'); }
    let data;
    try { data = await response.json(); } catch (_) { throw new Error('The service did not respond correctly. Please try again shortly.'); }
    if (!response.ok) {
      const detail = data.error || data.detail || data.message;
      if (response.status === 401 || response.status === 403) throw new Error('Authentication failed. Return to Telegram and reopen TimePocket.');
      throw new Error(typeof detail === 'string' ? detail : 'Unable to finish. Please try again shortly.');
    }
    return data;
  }
  async function refresh() {
    const version = ++loadVersion;
    const data = await api(`/api/state${selectedWeek ? `?week=${encodeURIComponent(selectedWeek)}` : ''}`);
    if (version !== loadVersion) return;
    state = data;
    state.projects = Array.isArray(data.projects) ? data.projects : [];
    state.logs = Array.isArray(data.logs) ? data.logs.filter((log) => log.ended_at !== null && log.ended_at !== undefined) : [];
    state.reminders = Array.isArray(data.reminders) ? data.reminders : [];
    selectedWeek = data.week;
    render();
  }
  async function mutate(path, payload, { form = null, dialog = null, message = 'Saved', onSuccess = null } = {}) {
    if (busy) return;
    busy = true;
    clearErrors();
    syncBusy();
    try {
      await api(path, payload);
      if (onSuccess) onSuccess();
      if (dialog) dialog.close();
      try { await refresh(); showNotice(message); }
      catch (error) { showNotice(`${message}. The latest data could not load. Refresh the page to confirm.`, true); }
    } catch (error) { showError(error, form); }
    finally { busy = false; syncBusy(); }
  }
  function renderOptions(id) {
    const select = $(id);
    const previous = select.value;
    select.replaceChildren(...state.projects.map((project) => {
      const option = element('option', '', project.name);
      option.value = project.id;
      return option;
    }));
    if (state.projects.some((project) => String(project.id) === previous)) select.value = previous;
  }
  function render() {
    $('main-content').hidden = false;
    $('loading').hidden = true;
    $('fatal-error').hidden = true;
    $('demo-banner').hidden = mode !== 'demo';
    $('timezone-label').textContent = state.timezone;
    $('greeting-date').textContent = new Intl.DateTimeFormat('en-US', { timeZone: state.timezone, month: 'long', day: 'numeric', weekday: 'long' }).format(new Date());
    $('current-week').textContent = `${state.week === currentWeek() ? 'This week · ' : ''}${weekText(state.week)}`;
    const actual = finite(state.total_actual);
    const budget = finite(state.total_budget);
    const remaining = Math.max(0, budget - actual);
    $('total-actual').textContent = hours(actual);
    $('total-budget').textContent = hours(budget);
    $('remaining-badge').textContent = actual > budget ? 'At your own pace' : `${hours(remaining)} h to spare`;
    const percentage = budget > 0 ? Math.min(100, actual / budget * 100) : (actual ? 100 : 0);
    $('summary-fill').style.width = `${percentage}%`;
    $('summary-progress').setAttribute('aria-valuemin', '0');
    $('summary-progress').setAttribute('aria-valuemax', String(Math.max(budget, actual, 1)));
    $('summary-progress').setAttribute('aria-valuenow', String(actual));
    $('summary-progress').setAttribute('aria-valuetext', `${hours(actual)} hours spent of a ${hours(budget)} hour budget`);
    $('summary-note').textContent = actual ? 'Every little effort leaves a mark' : 'Your own pace, one thing at a time';
    ['timer-project', 'entry-project', 'reminder-project'].forEach(renderOptions);
    if (state.timer) $('timer-project').value = state.timer.project_id;
    $('timer-project').disabled = !!state.timer || busy;
    $('timer-action-text').textContent = state.timer ? 'Finish focus' : 'Start focus';
    $('timer-toggle').classList.toggle('is-running', !!state.timer);
    $('timer-indicator').textContent = state.timer ? 'Focus in progress' : 'Ready when you are';
    $('timer-indicator').classList.toggle('running', !!state.timer);
    $('timer-hint').textContent = state.timer ? 'Stay in the moment. Reflect when you finish.' : 'A few minutes count, too';
    renderClock();
    renderProjects();
    renderReminders();
    renderStats();
    renderLogs();
    syncBusy();
  }
  function renderClock() {
    const seconds = state?.timer ? Math.max(0, Math.floor(Date.now() / 1000 - finite(state.timer.started_at))) : 0;
    const segments = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60];
    $('timer-clock').textContent = segments.map((value) => String(value).padStart(2, '0')).join(':');
    document.title = state?.timer ? `${segments.map((value) => String(value).padStart(2, '0')).join(':')} · TimePocket` : 'TimePocket · Make room for what matters';
  }
  function renderProjects() {
    $('project-list').replaceChildren(...state.projects.map((project) => {
      const card = element('article', 'project-card');
      setProjectColor(card, project.id);
      const top = element('div', 'project-top');
      const title = element('h3', 'project-name', project.name);
      const edit = element('button', 'budget-edit', '↗');
      edit.setAttribute('aria-label', `Edit the budget for ${project.name}`);
      edit.title = 'Edit budget';
      edit.addEventListener('click', () => openBudget(project));
      top.append(iconFor(project.id), title, edit);
      const numbers = element('div', 'project-numbers');
      const actual = element('span', 'actual-number', hours(project.actual_hours));
      actual.append(element('small', '', 'h'));
      numbers.append(actual, element('span', 'budget-number', `/ ${hours(project.budget_hours)} h budget`));
      const track = element('div', 'project-track');
      const fill = element('span');
      fill.style.width = `${project.budget_hours > 0 ? Math.min(100, finite(project.actual_hours) / project.budget_hours * 100) : project.actual_hours ? 100 : 0}%`;
      track.append(fill);
      const bottom = element('div', 'project-bottom');
      const remaining = finite(project.budget_hours) - finite(project.actual_hours);
      bottom.append(element('span', 'project-status', remaining >= 0 ? `${hours(remaining)} h to spare` : `${hours(-remaining)} h extra`));
      const focus = element('button', 'project-focus', state.timer && String(state.timer.project_id) === String(project.id) ? 'Focusing ·' : 'Focus ↗');
      focus.addEventListener('click', () => {
        if (state.timer) {
          showNotice('Finish your current session before starting another.');
          $('timer-toggle').scrollIntoView({ behavior: 'smooth', block: 'center' });
          return;
        }
        $('timer-project').value = project.id;
        $('timer-toggle').scrollIntoView({ behavior: 'smooth', block: 'center' });
        $('timer-toggle').focus({ preventScroll: true });
      });
      bottom.append(focus);
      card.append(top, numbers, track, bottom);
      return card;
    }));
  }
  function renderReminders() {
    const list = $('reminder-list');
    const reminders = [...state.reminders].sort((a, b) => finite(a.due_at) - finite(b.due_at));
    if (!reminders.length) {
      const empty = element('div', 'reminder-empty');
      empty.append(element('span', 'empty-icon', '♧'), element('p', '', 'No reminders for now'), element('p', 'empty-subtitle', 'Make a little room for something you want to do'));
      list.replaceChildren(empty);
      return;
    }
    list.replaceChildren(...reminders.map((reminder) => {
      const item = element('article', 'reminder-item');
      setProjectColor(item, reminder.project_id);
      const meta = element('div', 'reminder-meta');
      meta.append(element('span', 'mini-dot'), element('span', '', projectById(reminder.project_id)?.name || 'Project'));
      item.append(meta, element('h3', 'reminder-label', reminder.label), element('p', 'reminder-time', formattedDate(reminder.due_at)));
      const actionable = ['pending', 'sent', 'simulated', 'failed', 'uncertain'].includes(reminder.status);
      if (actionable) {
        const actions = element('div', 'reminder-actions');
        const snooze = element('button', '', 'In 15 minutes');
        const skip = element('button', '', 'Skip this time');
        snooze.addEventListener('click', () => mutate('/api/reminders/action', { id: reminder.id, action: 'snooze', minutes: 15 }, { message: 'Okay, another gentle nudge in 15 minutes' }));
        skip.addEventListener('click', () => mutate('/api/reminders/action', { id: reminder.id, action: 'skip', minutes: 15 }, { message: 'Skipped this time. Go at your own pace' }));
        actions.append(snooze, skip);
        item.append(actions);
      }
      if (reminder.status !== 'pending') item.append(element('p', 'reminder-state', statusNames[reminder.status] || reminder.status));
      return item;
    }));
  }
  function dailyTotals() {
    const days = Array.from({ length: 7 }, (_, index) => ({ day: shiftDate(state.week, index), hours: 0 }));
    for (const log of state.logs) {
      let start = finite(log.started_at);
      const end = finite(log.ended_at);
      if (end <= start) continue;
      for (const day of days) {
        const dayStart = inputToEpoch(`${day.day}T00:00`);
        const dayEnd = inputToEpoch(`${shiftDate(day.day, 1)}T00:00`);
        day.hours += Math.max(0, Math.min(end, dayEnd) - Math.max(start, dayStart)) / 3600;
      }
    }
    return days;
  }
  function renderStats() {
    $('review-hours').replaceChildren(document.createTextNode(`${hours(state.total_actual)} `), element('small', '', finite(state.total_actual) === 1 ? 'hour' : 'hours'));
    $('review-count').replaceChildren(document.createTextNode(`${state.logs.length} `), element('small', '', state.logs.length === 1 ? 'session' : 'sessions'));
    const activeProjects = state.projects.filter((project) => project.actual_hours > 0).length;
    $('review-projects').replaceChildren(document.createTextNode(`${activeProjects} `), element('small', '', activeProjects === 1 ? 'project' : 'projects'));
    const days = dailyTotals();
    const maxHours = Math.max(1, ...days.map((day) => day.hours));
    const today = localDate(Date.now() / 1000);
    $('daily-chart').replaceChildren(...days.map((day, index) => {
      const column = element('div', `day-column${day.day === today ? ' today' : ''}`);
      column.setAttribute('aria-label', `${day.day}: ${hours(day.hours)} hours`);
      const track = element('div', 'day-bar-track');
      const bar = element('span', 'day-bar');
      bar.style.height = `${Math.max(1.5, day.hours / maxHours * 100)}%`;
      track.append(bar);
      column.append(element('span', 'day-value', day.hours ? hours(day.hours) : '·'), track, element('span', 'day-label', ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][index]));
      return column;
    }));
    $('distribution-list').replaceChildren(...state.projects.map((project) => {
      const item = element('div', 'distribution-item');
      setProjectColor(item, project.id);
      const top = element('div', 'distribution-top');
      const name = element('span', 'distribution-name');
      name.append(element('span', 'mini-dot'), document.createTextNode(project.name));
      top.append(name, element('span', 'distribution-value', `${hours(project.actual_hours)} / ${hours(project.budget_hours)} h`));
      const track = element('div', 'project-track');
      const bar = element('span');
      bar.style.width = `${project.budget_hours > 0 ? Math.min(100, project.actual_hours / project.budget_hours * 100) : project.actual_hours ? 100 : 0}%`;
      track.append(bar);
      item.append(top, track);
      return item;
    }));
  }
  function renderLogs() {
    if (!state.logs.length) {
      const empty = element('div', 'card empty-logs');
      empty.append(element('span', 'empty-icon', '✧'), element('h2', '', 'This week’s story is just beginning'), element('p', '', 'Start a focus session or log time already spent.\nYou do not need a perfect plan to begin.'));
      const add = element('button', 'button secondary', 'Log my first session');
      add.addEventListener('click', () => openEntry(false));
      empty.append(add);
      $('logs-list').replaceChildren(empty);
      return;
    }
    $('logs-list').replaceChildren(...[...state.logs].sort((a, b) => b.started_at - a.started_at).map((log) => {
      const card = element('article', 'card log-card');
      const header = element('div', 'log-header');
      const duration = Math.max(0, finite(log.ended_at) - finite(log.started_at));
      header.append(iconFor(log.project_id), element('h3', 'log-title', projectById(log.project_id)?.name || 'Project'), element('span', 'log-duration', duration < 60 ? `${Math.round(duration)} sec` : `${hours(duration / 60)} min`));
      card.append(header, element('p', 'log-date', `${formattedDate(log.started_at)} — ${formattedDate(log.ended_at)} · ${state.timezone}`));
      const notes = element('div', 'log-notes');
      [['What you did', log.accomplishments], ['What got in the way', log.blockers], ['Next small step', log.next_steps]].forEach(([label, content]) => {
        if (!content) return;
        const note = element('div');
        note.append(element('p', 'log-note-label', label), element('p', 'log-note-content', content));
        notes.append(note);
      });
      if (notes.childElementCount) card.append(notes);
      return card;
    }));
  }
  function setView(view) {
    activeView = ['overview', 'week', 'logs'].includes(view) ? view : 'overview';
    document.querySelectorAll('.view-panel').forEach((panel) => { panel.hidden = panel.id !== `view-${activeView}`; });
    document.querySelectorAll('.nav-tab').forEach((button) => {
      const active = button.dataset.view === activeView;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    });
    const headings = { overview: ['Leave a little room this week', 'A time budget is a guide, not a deadline.'], week: ['Look back. Keep moving.', 'Notice your effort and the space around it.'], logs: ['Keep your progress close', 'A few notes can make the next start easier.'] };
    $('page-title').textContent = headings[activeView][0];
    $('page-subtitle').textContent = headings[activeView][1];
    history.replaceState(null, '', `#${activeView}`);
  }
  function openDialog(dialogId) {
    if (!state || busy) return;
    clearErrors();
    $(dialogId).showModal();
  }
  function openEntry(stopTimer) {
    if (!state || busy) return;
    $('entry-form').reset();
    entryTimerId = stopTimer ? state.timer?.id : null;
    if (stopTimer && !entryTimerId) return;
    entryRequestId = window.crypto?.randomUUID ? window.crypto.randomUUID() : `xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx`.replace(/[xy]/g, (char) => { const random = Math.random() * 16 | 0; return (char === 'x' ? random : (random & 3 | 8)).toString(16); });
    $('entry-title').textContent = stopTimer ? 'A little progress, well spent' : 'Save this little moment';
    $('entry-description').textContent = stopTimer ? 'Saving stops the timer. Capture a thought, then take a breath.' : 'A few words for your future self are enough.';
    $('entry-submit').textContent = stopTimer ? 'Stop timer and save' : 'Save this time';
    $('entry-manual-fields').hidden = stopTimer;
    $('entry-project').required = !stopTimer;
    $('entry-start').required = !stopTimer;
    $('entry-minutes').required = !stopTimer;
    if (!stopTimer) {
      $('entry-project').value = $('timer-project').value;
      $('entry-start').value = localInput(Date.now() / 1000 - 1800);
      $('entry-minutes').value = '30';
    }
    $('entry-timezone').textContent = `Times use ${state.timezone}`;
    openDialog('entry-dialog');
  }
  function openBudget(project) {
    editingProject = project;
    $('budget-name').value = project.name;
    $('budget-hours').value = project.budget_hours;
    $('budget-week').textContent = `Applies to the week of ${weekText(state.week)}`;
    openDialog('budget-dialog');
  }
  async function navigateWeek(offset) {
    if (busy || !state) return;
    const before = selectedWeek;
    selectedWeek = offset === 0 ? currentWeek() : shiftDate(state.week, offset * 7);
    busy = true; clearErrors(); syncBusy();
    try { await refresh(); } catch (error) { selectedWeek = before; showError(error); }
    finally { busy = false; syncBusy(); }
  }
  async function initialize() {
    if (busy) return;
    busy = true;
    $('fatal-error').hidden = true;
    $('loading').hidden = false;
    syncBusy();
    try {
      const response = await fetch('/api/config', { credentials: 'same-origin' });
      if (!response.ok) throw new Error('Unable to connect to the service. Please try again shortly.');
      const config = await response.json();
      mode = config.mode === 'production' ? 'production' : 'demo';
      if (mode === 'production' && window.Telegram?.WebApp) {
        window.Telegram.WebApp.ready();
        window.Telegram.WebApp.expand();
        if (typeof window.Telegram.WebApp.setHeaderColor === 'function') window.Telegram.WebApp.setHeaderColor('#f6f5ef');
      }
      await refresh();
      setView(location.hash.slice(1) || 'overview');
    } catch (error) {
      $('loading').hidden = true;
      $('fatal-message').textContent = error.message || 'There was a connection problem. Check your network and try again.';
      $('fatal-error').hidden = false;
    } finally { busy = false; syncBusy(); }
  }

  document.querySelectorAll('.nav-tab').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
  window.addEventListener('hashchange', () => setView(location.hash.slice(1)));
  document.querySelectorAll('.close-dialog').forEach((button) => button.addEventListener('click', () => { if (!busy) button.closest('dialog').close(); }));
  document.querySelectorAll('dialog').forEach((dialog) => dialog.addEventListener('cancel', (event) => { if (busy) event.preventDefault(); }));
  $('retry-load').addEventListener('click', initialize);
  $('previous-week').addEventListener('click', () => navigateWeek(-1));
  $('next-week').addEventListener('click', () => navigateWeek(1));
  $('current-week').addEventListener('click', () => navigateWeek(0));
  $('review-logs').addEventListener('click', () => setView('logs'));
  ['manual-log-open', 'logs-add'].forEach((id) => $(id).addEventListener('click', () => openEntry(false)));
  $('timer-toggle').addEventListener('click', () => {
    if (state.timer) openEntry(true);
    else mutate('/api/timer/start', { project_id: $('timer-project').value }, { message: 'You have started. One thing at a time is enough' });
  });
  $('entry-form').addEventListener('submit', (event) => {
    event.preventDefault();
    if (busy) return;
    const payload = { accomplishments: $('entry-accomplishments').value.trim(), blockers: $('entry-blockers').value.trim(), next_steps: $('entry-next').value.trim() };
    try {
      if (entryTimerId) payload.timer_id = entryTimerId;
      else {
        payload.project_id = $('entry-project').value;
        payload.started_at = inputToEpoch($('entry-start').value);
        payload.minutes = Number($('entry-minutes').value);
        payload.request_id = entryRequestId;
        if (payload.started_at + payload.minutes * 60 > Date.now() / 1000 + 60) throw new Error('This session has not ended yet. Check the start time and duration.');
      }
      mutate(entryTimerId ? '/api/timer/stop' : '/api/logs', payload, { form: event.currentTarget, dialog: $('entry-dialog'), message: 'Time saved. Every little effort counts', onSuccess: () => { entryRequestId = null; entryTimerId = null; } });
    } catch (error) { showError(error, event.currentTarget); }
  });
  $('budget-form').addEventListener('submit', (event) => {
    event.preventDefault();
    mutate('/api/projects', { id: editingProject.id, name: $('budget-name').value.trim(), budget_hours: Number($('budget-hours').value), week: state.week }, { form: event.currentTarget, dialog: $('budget-dialog'), message: 'Budget updated, with a little room for life' });
  });
  $('reminder-open').addEventListener('click', () => {
    $('reminder-form').reset();
    $('reminder-due').value = localInput(Date.now() / 1000 + 3600);
    $('reminder-timezone').textContent = `Times use ${state.timezone}${mode === 'demo' ? '; demo reminders are simulated and send no Telegram messages' : '; a reminder will reach you through Telegram'}`;
    openDialog('reminder-dialog');
  });
  $('reminder-form').addEventListener('submit', (event) => {
    event.preventDefault();
    if (busy) return;
    try {
      const due = inputToEpoch($('reminder-due').value);
      if (due <= Date.now() / 1000) throw new Error('Choose a time in the future.');
      mutate('/api/reminders', { project_id: $('reminder-project').value, label: $('reminder-label').value.trim(), due_at: due }, { form: event.currentTarget, dialog: $('reminder-dialog'), message: 'Reminder saved. See you then' });
    } catch (error) { showError(error, event.currentTarget); }
  });
  $('demo-reminder').addEventListener('click', () => mutate('/api/demo/remind', {}, { message: 'Demo reminder added. Try snoozing or skipping it under Gentle reminders' }));
  $('settings-open').addEventListener('click', () => {
    if (!state) return;
    $('settings-timezone').value = state.timezone;
    openDialog('settings-dialog');
  });
  $('settings-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const timezone = $('settings-timezone').value.trim();
    try { new Intl.DateTimeFormat('en-US', { timeZone: timezone }).format(); }
    catch (_) { showError(new Error('Time zone not recognized. Choose one from the list or enter a valid IANA time zone.'), event.currentTarget); return; }
    mutate('/api/settings', { timezone }, { form: event.currentTarget, dialog: $('settings-dialog'), message: 'Time zone updated', onSuccess: () => { selectedWeek = ''; } });
  });
  const zones = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : ['Asia/Shanghai', 'Asia/Singapore', 'Asia/Hong_Kong', 'Asia/Tokyo', 'Europe/London', 'America/New_York', 'America/Los_Angeles'];
  $('timezone-options').replaceChildren(...['UTC', ...zones].map((zone) => { const option = element('option'); option.value = zone; return option; }));
  setInterval(renderClock, 1000);
  function refreshWhenIdle() {
    if (!document.hidden && state && !busy && !document.querySelector('dialog[open]')) refresh().catch(() => {});
  }
  setInterval(refreshWhenIdle, 15000);
  document.addEventListener('visibilitychange', refreshWhenIdle);
  initialize();
})();
