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
let hrFilters = new URLSearchParams();

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

function renderRecommendations(recommendations, mode, onStart) {
  const content = element("div");
  if (mode === "llm") content.append(element("p", "mode-note", "Рекомендации подобраны AI на основе карьерной цели, разрывов по навыкам и истории участия."));
  if (mode === "rules_fallback") content.append(element("p", "mode-note", "Рекомендации построены проверяемыми правилами."));
  const list = element("div", "recommendation-list");
  if (!recommendations.length) list.append(element("p", "muted", "Сейчас нет доступных добровольных активностей, которые сокращают текущие разрывы."));
  recommendations.forEach(item => {
    const card = element("article", "recommendation");
    card.append(element("h3", "", item.title), element("p", "event-meta", `${item.format} · ${item.duration_hours} ч${item.next_session ? ` · ближайшая сессия ${item.next_session}` : " · доступно в своём темпе"}`));
    const evidence = element("ul", "evidence");
    item.evidence.forEach(reason => evidence.append(element("li", "", reason)));
    card.append(evidence);
    if (onStart) {
      const start = element("button", "", "Начать активность");
      start.addEventListener("click", () => onStart(item, start));
      card.append(start);
    }
    list.append(card);
  });
  content.append(list);
  return content;
}

function renderProfileInfo(profile) {
  const person = profile.employee;
  const card = element("section", "card");
  card.append(element("h2", "", "Текущая роль"), element("p", "profile-role", `${person.role} · ${person.grade}`));
  const facts = element("dl", "profile-facts");
  const workFormats = { office: "Офис", hybrid: "Гибрид", remote: "Удалённо" };
  [["Подразделение", person.department], ["Дата найма", person.hire_date], ["Стаж", `${person.tenure_months} мес.`], ["Формат работы", workFormats[person.work_format] || person.work_format], ["Последняя оценка", person.last_review_date]].forEach(([label, value]) => {
    const pair = element("div"); pair.append(element("dt", "muted", label), element("dd", "", value)); facts.append(pair);
  });
  card.append(facts); return card;
}

function createProfileTable(headers) {
  const wrap = element("div", "table-wrap analytics-table"); wrap.tabIndex = 0;
  const table = element("table"); const head = element("thead"); const row = element("tr");
  headers.forEach(label => { const cell = element("th", "", label); cell.scope = "col"; row.append(cell); });
  head.append(row); const body = element("tbody"); table.append(head, body); wrap.append(table);
  return { wrap, body };
}

function renderSkillProfile(profile) {
  const card = element("section", "card");
  card.append(element("h2", "", "Все навыки"), element("p", "muted", "Уровни от 0 до 5. Текущий уровень включает завершённые активности после последней оценки. Навыки без оценки считаются нулевыми."));
  const controls = element("div", "filters");
  const searchLabel = element("label", "", "Найти навык"); const search = element("input"); search.type = "search"; searchLabel.append(search);
  const scopeLabel = selectFilter("Показать", "skill_scope", [{ value: "target", label: "Навыки цели" }, { value: "gaps", label: "Только разрывы" }], "");
  const scope = scopeLabel.querySelector("select");
  controls.append(searchLabel, scopeLabel);
  const count = element("p", "muted");
  const { wrap, body } = createProfileTable(["Навык", "Тип", "Последняя оценка", "Сейчас", "Требование цели", "Разрыв"]);
  const renderRows = () => {
    const query = search.value.trim().toLocaleLowerCase();
    const visible = profile.skills.filter(skill => `${skill.name} ${skill.category}`.toLocaleLowerCase().includes(query) && (scope.value !== "target" || skill.required_level !== null) && (scope.value !== "gaps" || skill.gap > 0));
    body.replaceChildren(); count.textContent = `Показано: ${visible.length} из ${profile.skills.length}`;
    visible.forEach(skill => {
      const row = element("tr"); const name = element("td");
      name.append(element("strong", "", skill.name), element("p", "muted", skill.category)); name.title = skill.description;
      if (skill.is_critical) name.append(element("span", "critical", "КРИТИЧЕСКИЙ НАВЫК"));
      row.append(name, element("td", "", skill.type === "hard" ? "Профессиональный" : "Гибкий"), element("td", "", skill.assessed ? String(skill.assessed_level) : "Нет оценки (0)"), element("td", "", String(skill.current_level)), element("td", "", skill.required_level === null ? "—" : String(skill.required_level)), element("td", "", skill.gap === null ? "—" : String(skill.gap)));
      body.append(row);
    });
    if (!visible.length) { const row = element("tr"); const cell = element("td", "muted", "Нет навыков по выбранным условиям."); cell.colSpan = 6; row.append(cell); body.append(row); }
  };
  search.addEventListener("input", renderRows); scope.addEventListener("change", renderRows);
  renderRows(); card.append(controls, count, wrap); return card;
}

const activityStatusLabels = { completed: "Завершено", in_progress: "В процессе", dropped: "Прервано", no_show: "Неявка", declined: "Отказ", overdue: "Просрочено" };

function renderActivityHistory(profile) {
  const card = element("section", "card");
  card.append(element("h2", "", "История активностей"), element("p", "muted", "Вся история участия, включая завершения, пропуски и отказы. Дата участия — дата сессии или записи; дата завершения показана отдельно, когда она известна."));
  const controls = element("div", "filters");
  const searchLabel = element("label", "", "Найти активность"); const search = element("input"); search.type = "search"; searchLabel.append(search);
  const statusLabel = selectFilter("Статус", "history_status", Object.entries(activityStatusLabels).map(([value, label]) => ({ value, label })), "");
  const status = statusLabel.querySelector("select"); controls.append(searchLabel, statusLabel);
  const count = element("p", "muted");
  const { wrap, body } = createProfileTable(["Активность", "Дата участия", "Статус", "Выполнено", "Результат", "Изменение навыков"]);
  const renderRows = () => {
    const query = search.value.trim().toLocaleLowerCase();
    const visible = profile.history.filter(item => item.title.toLocaleLowerCase().includes(query) && (!status.value || item.status === status.value));
    body.replaceChildren(); count.textContent = `Показано: ${visible.length} из ${profile.history.length}`;
    visible.forEach(item => {
      const row = element("tr"); const title = element("td");
      const initiators = { self: "самостоятельно", manager: "руководитель", hr: "HR" };
      title.append(element("strong", "", item.title), element("p", "muted", `${item.mandatory ? "Обязательная" : "Добровольная"} · ${item.format} · инициатор: ${initiators[item.assigned_by] || item.assigned_by}`));
      const dates = element("td", "", item.activity_date);
      if (item.due_date) dates.append(element("p", "muted", `Срок: ${item.due_date}`));
      if (item.completed_at) dates.append(element("p", "muted", `Завершено: ${item.completed_at}`));
      const result = element("td");
      result.append(element("p", "", item.score === null ? "Результат не указан" : `Балл: ${item.score}/100`));
      if (item.feedback_rating !== null) result.append(element("p", "muted", `Отзыв: ${item.feedback_rating}/5`));
      const effects = element("td");
      if (item.skill_changes.length) item.skill_changes.forEach(change => effects.append(element("p", "", `${change.skill_name}: ${change.before_level} → ${change.after_level}`)));
      else {
        const messages = { included_in_assessment: "Учтено в последней оценке навыков.", no_skill_change: "Активность не меняет уровни навыков.", not_completed: "Прирост не начислен: активность не завершена." };
        effects.append(element("span", "muted", messages[item.skill_effect] || "Нет изменений навыков."));
      }
      row.append(title, dates, element("td", "", activityStatusLabels[item.status] || item.status), element("td", "", `${item.completion_pct}%`), result, effects); body.append(row);
    });
    if (!visible.length) { const row = element("tr"); const cell = element("td", "muted", profile.history.length ? "Нет активностей по выбранным условиям." : "История участия пока пуста."); cell.colSpan = 6; row.append(cell); body.append(row); }
  };
  search.addEventListener("input", renderRows); status.addEventListener("change", renderRows);
  renderRows(); card.append(controls, count, wrap); return card;
}

function renderGoalForm(profile, trajectory) {
  const form = element("form", "goal-form");
  const roleLabel = element("label", "", "Целевая роль"); const role = element("select"); role.name = "target_role"; role.required = true; role.setAttribute("aria-label", "Целевая роль");
  [...new Set(profile.goal_options.map(item => item.role))].forEach(value => { const option = element("option", "", value); option.value = value; role.append(option); });
  role.value = trajectory.target ? trajectory.target.role : profile.employee.role; roleLabel.append(role);
  const gradeLabel = element("label", "", "Целевой грейд"); const grade = element("select"); grade.name = "target_grade"; grade.required = true; grade.setAttribute("aria-label", "Целевой грейд"); gradeLabel.append(grade);
  const fillGrades = selected => {
    grade.replaceChildren(); const placeholder = element("option", "", "Выберите грейд"); placeholder.value = ""; grade.append(placeholder);
    profile.goal_options.filter(item => item.role === role.value).forEach(item => { const option = element("option", "", item.grade); option.value = item.grade; grade.append(option); });
    grade.value = selected;
  };
  fillGrades(trajectory.target ? trajectory.target.grade : ""); role.addEventListener("change", () => fillGrades(""));
  const error = element("p", "error"); error.hidden = true; error.setAttribute("role", "alert");
  const save = element("button", "", "Сохранить цель"); save.type = "submit";
  const clear = element("button", "secondary", profile.employee.grade === "Lead" ? "Убрать цель" : "Следующий грейд по умолчанию"); clear.type = "button"; clear.hidden = !profile.employee.target_role;
  const persist = async (targetRole, targetGrade, button) => {
    showError(error, ""); [role, grade, save, clear].forEach(control => { control.disabled = true; });
    try {
      await withLoading(button, "Сохраняем…", async () => {
        await request("/api/employee/goal", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target_role: targetRole, target_grade: targetGrade }) });
        await showEmployee();
      });
    } catch (problem) { showError(error, problem.message); }
    finally { [role, grade, save, clear].forEach(control => { control.disabled = false; }); }
  };
  form.addEventListener("submit", event => { event.preventDefault(); return persist(role.value, grade.value, save); });
  clear.addEventListener("click", () => persist(null, null, clear));
  form.append(roleLabel, gradeLabel, error, save, clear); return form;
}

function renderDashboard(data) {
  const { profile, trajectory, recommendations, recommendation_mode: mode, active_enrollments: activeEnrollments, demo_mode: demoMode, is_demo_user: isDemoUser } = data;
  document.querySelector("#employee-name").textContent = trajectory.employee.full_name;
  document.querySelector("#user-role").textContent = "Сотрудник";
  employeeDemoMode = demoMode;
  resetButton.hidden = !(demoMode && isDemoUser);
  const root = document.querySelector("#employee-content");
  root.replaceChildren();

  const dashboard = element("div", "dashboard");
  dashboard.append(renderProfileInfo(profile));
  const summary = element("div", "summary");
  const target = element("section", "card");
  target.append(element("p", "eyebrow", "ВАША ЦЕЛЬ"), element("h2", "", trajectory.target ? `${trajectory.target.role} · ${trajectory.target.grade}` : "Выберите карьерную цель"));
  target.append(element("p", "muted", trajectory.target ? "Требования цели сопоставлены с актуальными навыками, включая завершённые активности после последней оценки." : "Выберите роль и грейд, чтобы увидеть требования и следующие шаги развития."));
  if (trajectory.target && !profile.employee.target_role) target.append(element("p", "muted", "По умолчанию выбран следующий грейд в текущей роли."));
  const goalEditor = element("details", "goal-editor"); goalEditor.open = !trajectory.target;
  goalEditor.append(element("summary", "", trajectory.target ? "Изменить цель" : "Выбрать роль и грейд"), renderGoalForm(profile, trajectory)); target.append(goalEditor);
  const coverage = element("section", "card");
  coverage.append(element("p", "eyebrow", "ПОКРЫТИЕ ТРЕБОВАНИЙ"), element("div", "metric", trajectory.coverage_percent === null ? "—" : `${trajectory.coverage_percent}%`));
  const progress = element("div", "progress");
  const bar = element("span"); bar.style.width = `${Math.max(0, Math.min(100, trajectory.coverage_percent))}%`;
  progress.append(bar); coverage.append(progress, element("p", "muted", trajectory.target ? "Это показатель покрытия навыков, а не гарантия повышения." : "Покрытие появится после выбора цели."));
  summary.append(target, coverage); dashboard.append(summary);

  const recommendationsCard = element("section", "card");
  recommendationsCard.append(element("h2", "", "Следующие шаги"));
  recommendationsCard.append(trajectory.target ? renderRecommendations(recommendations, mode, startActivity) : element("p", "muted", "Выберите карьерную цель, чтобы получить рекомендации."));
  dashboard.append(recommendationsCard); root.append(dashboard);

  if (activeEnrollments.length) {
    const active = element("section", "card"); active.append(element("h2", "", "В процессе"));
    activeEnrollments.forEach(item => {
      const row = element("article", "recommendation"); row.append(element("h3", "", item.title), element("p", "event-meta", `${item.format} · ${item.duration_hours} ч · начато ${item.registered_at}`));
      if (demoMode) { const open = element("button", "", "Открыть активность"); open.addEventListener("click", () => openActivityModal(item, item.enrollment_id)); row.append(open); }
      active.append(row);
    }); dashboard.append(active);
  }
  dashboard.append(renderSkillProfile(profile), renderActivityHistory(profile));
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
  if (!window.confirm("Сбросить только ваш демо-прогресс? Начатые и завершённые через приложение активности будут удалены, карьерная цель вернётся к исходной.")) return;
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
  const wrapper = element("label", "", label); const select = element("select"); select.name = name; select.setAttribute("aria-label", label);
  const all = element("option", "", "Все"); all.value = ""; select.append(all);
  values.forEach(item => { const value = typeof item === "string" ? item : item.value; const option = element("option", "", typeof item === "string" ? item : item.label); option.value = value; option.selected = value === selected; select.append(option); });
  wrapper.append(select); return wrapper;
}

function renderHrDetail(detail) {
  const root = document.querySelector("#hr-content");
  const card = element("section", "card");
  card.append(element("h2", "", detail.employee.full_name), element("p", "muted", `${detail.employee.department} · ${detail.employee.role} · ${detail.employee.grade}`));
  if (detail.trajectory.target) card.append(element("p", "", `Цель: ${detail.trajectory.target.role} · ${detail.trajectory.target.grade}; покрытие требований: ${detail.trajectory.coverage_percent}%`));
  else card.append(element("p", "muted", "Карьерная цель не задана. Сотрудник может выбрать её в своём профиле."));
  const rec = element("div", ""); rec.append(element("h3", "", "Доступные следующие шаги"));
  rec.append(renderRecommendations(detail.recommendations, detail.recommendation_mode)); card.append(rec);
  const back = element("button", "secondary", "Вернуться к обзору"); back.addEventListener("click", () => withLoading(back, "Загружаем…", showHr)); card.append(back);
  root.replaceChildren(card, renderProfileInfo(detail.profile), renderSkillProfile(detail.profile), renderActivityHistory(detail.profile));
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

function renderHrPeople(data) {
  const people = element("section", "card");
  people.append(element("h2", "", "Сотрудники и следующие шаги"), element("p", "muted", `Участие с ${data.support_period_start} по ${data.as_of_date} включительно. Сигналы помогают предложить поддержку, а не оценивают эффективность.`));
  const wrap = element("div", "table-wrap analytics-table"); const table = element("table");
  const head = element("thead"); const header = element("tr");
  ["Сотрудник", "Роль", "Покрытие", "Следующий шаг", "Сигналы поддержки"].forEach(value => { const th = element("th", "", value); th.scope = "col"; header.append(th); });
  head.append(header); table.append(head);
  const body = element("tbody");
  if (!data.employees.length) { const row = element("tr"); const cell = element("td", "muted", "Нет сотрудников по выбранным фильтрам."); cell.colSpan = 5; row.append(cell); body.append(row); }
  data.employees.forEach(person => {
    const row = element("tr");
    const name = element("button", "secondary", person.full_name);
    name.addEventListener("click", () => withLoading(name, "Загружаем…", () => showHrDetail(person.employee_id)));
    const cell = element("td"); cell.append(name);
    row.append(cell, element("td", "", `${person.role} · ${person.grade}`), element("td", "", person.coverage_percent === null ? "Цель не задана" : `${person.coverage_percent}%`));
    const nextStep = element("td");
    if (person.next_step.has_next_step) {
      nextStep.append(element("span", "", `Доступных активностей: ${person.next_step.eligible_event_count}`));
    } else {
      nextStep.append(element("strong", "", "Нет следующего шага"));
      const reasons = element("ul", "availability-reasons");
      person.next_step.reasons.forEach(reason => reasons.append(element("li", "", `${reason.message}${reason.event_count ? ` Активностей: ${reason.event_count}.` : ""}`)));
      nextStep.append(reasons);
    }
    const signals = element("td");
    if (person.support_signals.length) person.support_signals.forEach(signal => signals.append(element("p", "signal", signal)));
    else signals.append(element("span", "muted", "Нет"));
    row.append(nextStep, signals); body.append(row);
  });
  table.append(body); wrap.append(table); people.append(wrap);
  return people;
}

function renderActivityParticipation(data) {
  const section = element("section", "card");
  section.append(element("h2", "", "Участие по активностям"), element("p", "muted", `С ${data.support_period_start} по ${data.as_of_date} включительно, для сотрудников по выбранным фильтрам. Доля завершений — завершённые записи / все записи участия. Повторные участия считаются отдельно, сотрудники — один раз в каждой активности.`));
  if (!data.activity_participation.length) { section.append(element("p", "muted", "Нет сотрудников по выбранным фильтрам.")); return section; }
  if (!data.activity_participation.some(item => item.total_records)) section.append(element("p", "muted", "За этот период нет записей участия."));
  const wrap = element("div", "table-wrap analytics-table"); const table = element("table");
  const head = element("thead"); const header = element("tr");
  ["Активность", "Записи / сотрудники", "Завершено", "В процессе", "Брошено", "Неявки", "Отказы", "Просрочено", "Доля завершений"].forEach(value => { const th = element("th", "", value); th.scope = "col"; header.append(th); });
  head.append(header); table.append(head);
  const body = element("tbody");
  data.activity_participation.forEach(item => {
    const row = element("tr"); const title = element("td");
    title.append(element("strong", "", item.title), element("p", "muted", item.mandatory ? "Обязательная" : "Добровольная"));
    row.append(title, element("td", "", `${item.total_records} / ${item.unique_participants}`));
    ["completed", "in_progress", "dropped", "no_show", "declined", "overdue"].forEach(status => row.append(element("td", "", String(item.status_counts[status]))));
    row.append(element("td", "", item.completion_rate_percent === null ? "—" : `${item.completion_rate_percent}%`));
    body.append(row);
  });
  table.append(body); wrap.append(table); section.append(wrap);
  return section;
}

function renderHrDashboard(data) {
  const root = document.querySelector("#hr-content"); root.replaceChildren();
  const filters = element("form", "filters");
  filters.append(selectFilter("Подразделение", "department", data.filter_options.departments, data.filters.department), selectFilter("Роль", "role", data.filter_options.roles, data.filters.role), selectFilter("Грейд", "grade", data.filter_options.grades, data.filters.grade));
  filters.append(selectFilter("Следующий шаг", "next_step", [{ value: "missing", label: "Без следующего шага" }, { value: "available", label: "Есть доступные активности" }], data.filters.next_step));
  const apply = element("button", "", "Применить"); apply.type = "submit"; filters.append(apply);
  filters.addEventListener("submit", event => { event.preventDefault(); const params = new URLSearchParams(new FormData(filters)); [...params.keys()].forEach(key => !params.get(key) && params.delete(key)); withLoading(apply, "Загружаем…", () => showHr(params)); }); root.append(filters);

  const stats = element("div", "stat-grid");
  [["Сотрудников", data.summary.employees], ["Без следующего шага", data.summary.without_next_step], ["Нужна поддержка", data.summary.needs_support], ["Компетенций с разрывами", data.summary.competencies_with_gaps]].forEach(([label, value]) => { const item = element("div", "stat"); item.append(element("strong", "", String(value)), element("span", "muted", label)); stats.append(item); }); root.append(stats);

  const competency = element("section", "card"); competency.append(element("h2", "", "Проседающие компетенции"), element("p", "muted", "Агрегированный срез по разрывам карьерных целей. Это не рейтинг сотрудников."));
  const competencyList = element("ul", "gap-list"); data.competency_gaps.slice(0, 10).forEach(item => competencyList.append(element("li", "", `${item.skill_name}: ${item.employees_affected} сотрудников, суммарный разрыв ${item.total_gap}${item.critical_gap_count ? ` · критический у ${item.critical_gap_count}` : ""}`))); competency.append(competencyList); root.append(competency);
  if (!data.competency_gaps.length) competency.append(element("p", "muted", "Нет разрывов по выбранным фильтрам."));
  root.append(renderActivityParticipation(data), renderHrPeople(data));

  const upload = element("section", "card"); upload.append(element("h2", "", "Загрузить проверочные данные"), element("p", "muted", "Выберите employees.json и activity_history.csv в исходной схеме набора. Импорт проверяется до изменения базы."));
  const uploadForm = element("form", "upload"); const employeeInput = element("input"); employeeInput.id = "employees-file"; employeeInput.type = "file"; employeeInput.accept = ".json,application/json"; const historyInput = element("input"); historyInput.id = "history-file"; historyInput.type = "file"; historyInput.accept = ".csv,text/csv"; const submit = element("button", "", "Проверить и импортировать"); submit.type = "submit"; uploadForm.append(element("label", "", "employees.json"), employeeInput, element("label", "", "activity_history.csv"), historyInput, submit); uploadForm.addEventListener("submit", event => { event.preventDefault(); withLoading(submit, "Импортируем…", () => importProfiles(uploadForm)); }); upload.append(uploadForm); root.append(upload);
}

async function showHr(params = hrFilters) {
  try { const suffix = params.toString() ? `?${params}` : ""; const data = await request(`/api/hr/dashboard${suffix}`); hrFilters = new URLSearchParams(params); loginView.hidden = true; employeeView.hidden = true; hrView.hidden = false; showError(hrError, ""); renderHrDashboard(data); }
  catch (error) { showError(hrError, error.message); }
}

restoreSession();
