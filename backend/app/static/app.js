const loginView = document.querySelector("#login-view");
const employeeView = document.querySelector("#employee-view");
const hrView = document.querySelector("#hr-view");
const loginError = document.querySelector("#login-error");
const pageError = document.querySelector("#page-error");
const hrError = document.querySelector("#hr-error");
const resetButton = document.querySelector("#reset-button");
const activityModal = document.querySelector("#activity-modal");
const modalTitle = document.querySelector("#activity-modal-title");
const modalMeta = document.querySelector("#activity-modal-meta");
const modalBenefits = document.querySelector("#activity-modal-benefits");
const modalCompleteButton = document.querySelector("#modal-complete-button");
let employeeDemoMode = false;

async function request(path, options = {}) {
  const response = await fetch(path, { credentials: "same-origin", ...options });
  const payload = response.status === 204 ? {} : await response.json();
  if (!response.ok) throw new Error(payload.error || "Не удалось выполнить запрос");
  return payload;
}

function showError(element, message) {
  element.textContent = message;
  element.hidden = !message;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function withLoading(button, loadingText, action) {
  const originalText = button.textContent;
  button.disabled = true; button.classList.add("loading"); button.textContent = loadingText;
  try { return await action(); }
  finally { button.disabled = false; button.classList.remove("loading"); button.textContent = originalText; }
}

function renderDashboard(data) {
  const { trajectory, recommendations, recommendation_mode: mode, recommendation_notice: notice, active_enrollments: activeEnrollments, demo_mode: demoMode, is_demo_user: isDemoUser } = data;
  document.querySelector("#employee-name").textContent = trajectory.employee.full_name;
  document.querySelector("#user-role").textContent = "Сотрудник";
  employeeDemoMode = demoMode;
  resetButton.hidden = !(demoMode && isDemoUser);
  const root = document.querySelector("#employee-content");
  root.replaceChildren();

  if (trajectory.trajectory_status !== "ready") {
    const card = element("section", "card");
    card.append(element("h2", "", "Выберите карьерную цель"), element("p", "muted", trajectory.message));
    root.append(card);
    return;
  }
  const dashboard = element("div", "dashboard");
  const summary = element("div", "summary");
  const target = element("section", "card");
  target.append(element("p", "eyebrow", "ВАША ЦЕЛЬ"), element("h2", "", `${trajectory.target.role} · ${trajectory.target.grade}`));
  target.append(element("p", "muted", "Требования цели сопоставлены с актуальными навыками, включая завершённые активности после последней оценки."));
  const coverage = element("section", "card");
  coverage.append(element("p", "eyebrow", "ПОКРЫТИЕ ТРЕБОВАНИЙ"), element("div", "metric", `${trajectory.coverage_percent}%`));
  const progress = element("div", "progress");
  const bar = element("span"); bar.style.width = `${Math.max(0, Math.min(100, trajectory.coverage_percent))}%`;
  progress.append(bar); coverage.append(progress, element("p", "muted", "Это показатель покрытия навыков, а не гарантия повышения."));
  summary.append(target, coverage); dashboard.append(summary);

  const grid = element("div", "grid");
  const gaps = element("section", "card"); gaps.append(element("h2", "", "Навыки для следующего шага"));
  const gapList = element("ul", "gap-list");
  const visibleGaps = trajectory.skill_gaps.filter(item => item.gap > 0).slice(0, 7);
  if (!visibleGaps.length) gapList.append(element("li", "muted", "Все требования по навыкам уже покрыты."));
  visibleGaps.forEach(item => {
    const row = element("li", "gap"); const left = element("div");
    left.append(element("strong", "", item.skill_name));
    if (item.is_critical) left.append(element("span", "critical", "КРИТИЧЕСКИЙ НАВЫК"));
    const right = element("small", "", `${item.current_level} / ${item.required_level} · разрыв ${item.gap}`);
    row.append(left, right); gapList.append(row);
  }); gaps.append(gapList); grid.append(gaps);
  const updates = element("section", "card"); updates.append(element("h2", "", "Учтённый прогресс"));
  const changes = trajectory.applied_skill_changes;
  if (!changes.length) updates.append(element("p", "muted", "После последней оценки пока нет завершённых активностей с приростом навыков."));
  changes.slice(-5).reverse().forEach(change => updates.append(element("p", "", `${change.event_title}: ${change.skill_id} ${change.before_level} → ${change.after_level}`)));
  grid.append(updates); dashboard.append(grid);

  const recommendationsCard = element("section", "card");
  recommendationsCard.append(element("h2", "", "Следующие шаги"));
  if (mode === "llm") recommendationsCard.append(element("p", "mode-note", "AI-режим включён: модель выбрала шаги из проверенного сервером списка."));
  if (mode === "rules_fallback") recommendationsCard.append(element("p", "mode-note", "Рекомендации построены проверяемыми правилами. Полный AI-режим подключается через конфигурацию модели."));
  if (notice && mode !== "rules_fallback") recommendationsCard.append(element("p", "mode-note", notice));
  const recommendationList = element("div", "recommendation-list");
  if (!recommendations.length) recommendationList.append(element("p", "muted", "Сейчас нет доступных добровольных активностей, которые сокращают текущие разрывы."));
  recommendations.forEach(item => {
    const card = element("article", "recommendation");
    card.append(element("h3", "", item.title), element("p", "event-meta", `${item.format} · ${item.duration_hours} ч${item.next_session ? ` · ближайшая сессия ${item.next_session}` : " · доступно в своём темпе"}`));
    const evidence = element("ul", "evidence"); item.evidence.forEach(reason => evidence.append(element("li", "", reason))); card.append(evidence);
    const start = element("button", "", "Начать активность");
    start.addEventListener("click", () => startActivity(item, start)); card.append(start); recommendationList.append(card);
  }); recommendationsCard.append(recommendationList); dashboard.append(recommendationsCard); root.append(dashboard);

  if (activeEnrollments.length) {
    const active = element("section", "card"); active.append(element("h2", "", "В процессе"));
    activeEnrollments.forEach(item => {
      const row = element("article", "recommendation"); row.append(element("h3", "", item.title), element("p", "event-meta", `${item.format} · ${item.duration_hours} ч · начато ${item.registered_at}`));
      if (demoMode) { const open = element("button", "", "Открыть активность"); open.addEventListener("click", () => openActivityModal(item, item.enrollment_id)); row.append(open); }
      active.append(row);
    }); dashboard.append(active);
  }
}

async function showEmployee() {
  const data = await request("/api/employee/dashboard");
  loginView.hidden = true; hrView.hidden = true; employeeView.hidden = false; showError(pageError, ""); renderDashboard(data);
}

function openActivityModal(activity, enrollmentId) {
  modalTitle.textContent = activity.title;
  modalMeta.textContent = `${activity.format} · ${activity.duration_hours} ч`;
  modalBenefits.replaceChildren();
  modalCompleteButton.hidden = !employeeDemoMode;
  const benefits = activity.expected_skill_changes || [];
  if (benefits.length) benefits.forEach(change => modalBenefits.append(element("li", "", `${change.skill_name}: ${change.before_level} → ${change.after_level}${change.required_level !== null ? ` при требовании ${change.required_level}` : ""}`)));
  else modalBenefits.append(element("li", "", "Активность уже начата. Завершение в демо обновит историю и прогресс."));
  modalCompleteButton.onclick = () => completeEnrollment(enrollmentId, modalCompleteButton);
  activityModal.showModal();
}

async function startActivity(item, button) {
  try {
    await withLoading(button, "Начинаем…", async () => {
      const result = await request(`/api/employee/activities/${encodeURIComponent(item.event_id)}/enroll`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      openActivityModal(item, result.enrollment.enrollment_id);
      await showEmployee();
    });
  }
  catch (error) { showError(pageError, error.message); }
}

async function completeEnrollment(enrollmentId, button) {
  try {
    await withLoading(button, "Засчитываем…", async () => {
      await request(`/api/employee/enrollments/${encodeURIComponent(enrollmentId)}/complete`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      activityModal.close(); await showEmployee();
    });
  }
  catch (error) { showError(pageError, error.message); }
}

async function resetDemo(button) {
  if (!window.confirm("Сбросить только ваш демо-прогресс? Начатые и завершённые через приложение активности будут удалены.")) return;
  try { await withLoading(button, "Сбрасываем…", async () => { await request("/api/employee/demo-reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); await showEmployee(); }); }
  catch (error) { showError(pageError, error.message); }
}

async function restoreSession() {
  try {
    const user = await request("/api/me");
    if (user.access_role === "hr") { await showHr(); return; }
    await showEmployee();
  } catch (_) { loginView.hidden = false; employeeView.hidden = true; hrView.hidden = true; }
}

document.querySelector("#login-form").addEventListener("submit", async event => {
  event.preventDefault(); showError(loginError, "");
  const form = new FormData(event.currentTarget);
  try {
    await withLoading(event.currentTarget.querySelector("button[type=submit]"), "Входим…", async () => {
      const user = await request("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: form.get("username"), password: form.get("password") }) });
      if (user.access_role === "hr") { await showHr(); return; }
      await showEmployee();
    });
  } catch (error) { showError(loginError, error.message); }
});

async function logout() { await request("/api/logout", { method: "POST" }); window.location.reload(); }
document.querySelector("#logout-button").addEventListener("click", event => withLoading(event.currentTarget, "Выходим…", logout));
document.querySelector("#hr-logout-button").addEventListener("click", event => withLoading(event.currentTarget, "Выходим…", logout));
resetButton.addEventListener("click", () => resetDemo(resetButton));

function selectFilter(label, name, values, selected) {
  const wrapper = element("label", "", label); const select = element("select"); select.name = name;
  const all = element("option", "", "Все"); all.value = ""; select.append(all);
  values.forEach(value => { const option = element("option", "", value); option.value = value; option.selected = value === selected; select.append(option); });
  wrapper.append(select); return wrapper;
}

function renderHrDetail(detail) {
  const root = document.querySelector("#hr-content");
  const card = element("section", "card");
  card.append(element("h2", "", detail.employee.full_name), element("p", "muted", `${detail.employee.department} · ${detail.employee.role} · ${detail.employee.grade}`));
  if (detail.trajectory.target) card.append(element("p", "", `Цель: ${detail.trajectory.target.role} · ${detail.trajectory.target.grade}; покрытие требований: ${detail.trajectory.coverage_percent}%`));
  const gaps = detail.trajectory.skill_gaps.filter(item => item.gap > 0).slice(0, 8);
  const list = element("ul", "gap-list"); gaps.forEach(item => list.append(element("li", "", `${item.skill_name}: ${item.current_level}/${item.required_level}${item.is_critical ? " · критический" : ""}`))); card.append(list);
  const rec = element("div", ""); rec.append(element("h3", "", "Доступные следующие шаги"));
  detail.recommendations.forEach(item => rec.append(element("p", "", item.title))); card.append(rec);
  const back = element("button", "secondary", "Вернуться к обзору"); back.addEventListener("click", () => withLoading(back, "Загружаем…", showHr)); card.append(back);
  root.replaceChildren(card);
}

async function showHrDetail(employeeId) {
  try { showError(hrError, ""); renderHrDetail(await request(`/api/hr/employees/${encodeURIComponent(employeeId)}`)); }
  catch (error) { showError(hrError, error.message); }
}

async function importProfiles(form) {
  try {
    const employeesFile = form.querySelector("#employees-file").files[0];
    const historyFile = form.querySelector("#history-file").files[0];
    if (!employeesFile || !historyFile) throw new Error("Выберите employees.json и activity_history.csv.");
    const result = await request("/api/hr/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ employees_json: await employeesFile.text(), history_csv: await historyFile.text() }) });
    showError(hrError, ""); alert(`Импортировано: профилей ${result.employees_imported}, записей истории ${result.history_records_imported}.`); await showHr();
  } catch (error) { showError(hrError, error.message); }
}

function renderHrDashboard(data) {
  const root = document.querySelector("#hr-content"); root.replaceChildren();
  const filters = element("form", "filters");
  filters.append(selectFilter("Подразделение", "department", data.filter_options.departments, data.filters.department), selectFilter("Роль", "role", data.filter_options.roles, data.filters.role), selectFilter("Грейд", "grade", data.filter_options.grades, data.filters.grade));
  const apply = element("button", "", "Применить"); apply.type = "submit"; filters.append(apply);
  filters.addEventListener("submit", event => { event.preventDefault(); const params = new URLSearchParams(new FormData(filters)); [...params.keys()].forEach(key => !params.get(key) && params.delete(key)); withLoading(apply, "Загружаем…", () => showHr(params)); }); root.append(filters);

  const stats = element("div", "stat-grid");
  [["Сотрудников", data.summary.employees], ["Нужна поддержка", data.summary.needs_support], ["Компетенций с разрывами", data.summary.competencies_with_gaps]].forEach(([label, value]) => { const item = element("div", "stat"); item.append(element("strong", "", String(value)), element("span", "muted", label)); stats.append(item); }); root.append(stats);

  const competency = element("section", "card"); competency.append(element("h2", "", "Проседающие компетенции"), element("p", "muted", "Агрегированный срез по разрывам карьерных целей. Это не рейтинг сотрудников."));
  const competencyList = element("ul", "gap-list"); data.competency_gaps.slice(0, 10).forEach(item => competencyList.append(element("li", "", `${item.skill_name}: ${item.employees_affected} сотрудников, суммарный разрыв ${item.total_gap}${item.critical_gap_count ? ` · критический у ${item.critical_gap_count}` : ""}`))); competency.append(competencyList); root.append(competency);

  const people = element("section", "card"); people.append(element("h2", "", "Сигналы поддержки"), element("p", "muted", `Период участия: с ${data.support_period_start}. Сигналы помогают предложить поддержку, а не оценивают эффективность.`));
  const tableWrap = element("div", "table-wrap"); const table = element("table");
  const head = element("thead"); const header = element("tr"); ["Сотрудник", "Роль", "Покрытие", "Сигналы"].forEach(value => header.append(element("th", "", value))); head.append(header); table.append(head);
  const body = element("tbody"); data.employees.forEach(person => { const row = element("tr"); const name = element("button", "secondary", person.full_name); name.addEventListener("click", () => showHrDetail(person.employee_id)); const cell = element("td"); cell.append(name); row.append(cell, element("td", "", `${person.role} · ${person.grade}`), element("td", "", person.coverage_percent === null ? "Цель не задана" : `${person.coverage_percent}%`)); const signals = element("td"); if (person.support_signals.length) person.support_signals.forEach(signal => signals.append(element("p", "signal", signal))); else signals.append(element("span", "muted", "Нет")); row.append(signals); body.append(row); }); table.append(body); tableWrap.append(table); people.append(tableWrap); root.append(people);

  const upload = element("section", "card"); upload.append(element("h2", "", "Загрузить проверочные данные"), element("p", "muted", "Выберите employees.json и activity_history.csv в исходной схеме набора. Импорт проверяется до изменения базы."));
  const uploadForm = element("form", "upload"); const employeeInput = element("input"); employeeInput.id = "employees-file"; employeeInput.type = "file"; employeeInput.accept = ".json,application/json"; const historyInput = element("input"); historyInput.id = "history-file"; historyInput.type = "file"; historyInput.accept = ".csv,text/csv"; const submit = element("button", "", "Проверить и импортировать"); submit.type = "submit"; uploadForm.append(element("label", "", "employees.json"), employeeInput, element("label", "", "activity_history.csv"), historyInput, submit); uploadForm.addEventListener("submit", event => { event.preventDefault(); withLoading(submit, "Импортируем…", () => importProfiles(uploadForm)); }); upload.append(uploadForm); root.append(upload);
}

async function showHr(params = new URLSearchParams()) {
  try { const suffix = params.toString() ? `?${params}` : ""; const data = await request(`/api/hr/dashboard${suffix}`); loginView.hidden = true; employeeView.hidden = true; hrView.hidden = false; showError(hrError, ""); renderHrDashboard(data); }
  catch (error) { showError(hrError, error.message); }
}

restoreSession();
