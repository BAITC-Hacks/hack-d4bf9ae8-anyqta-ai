const $ = selector => document.querySelector(selector);
const loginView = $("#login-view");
const employeeView = $("#employee-view");
const hrView = $("#hr-view");
const loginError = $("#login-error");
const pageError = $("#page-error");
const hrError = $("#hr-error");
const resetButton = $("#reset-button");
const activityModal = $("#activity-modal");
const modalCompleteButton = $("#modal-complete-button");
let employeeDemoMode = false;
let viewVersion = 0;
let recommendationRequest;
let lastCompletion;
let lastImport;
let hrFilters = new URLSearchParams();
const formats = { online: "Онлайн", offline: "Очно", self_paced: "В своём темпе" };
const statuses = { completed: "Завершено", in_progress: "В процессе", dropped: "Не завершено", no_show: "Пропуск", declined: "Отказ", overdue: "Просрочено" };

async function request(path, options = {}) {
  const response = await fetch(path, { credentials: "same-origin", ...options });
  const payload = response.status === 204 ? {} : await response.json();
  if (!response.ok) throw new Error(payload.error || "Не удалось выполнить запрос");
  return payload;
}
const post = (path, body = {}) => request(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
function showError(node, message) { node.textContent = message; node.hidden = !message; }
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function button(text, action, secondary = false) {
  const node = element("button", secondary ? "secondary" : "", text);
  node.type = "button"; node.addEventListener("click", () => action(node)); return node;
}
async function withLoading(node, text, action) {
  const original = node.textContent;
  node.disabled = true; node.classList.add("loading"); node.textContent = text; node.setAttribute("aria-busy", "true");
  try { return await action(); }
  finally { node.disabled = false; node.classList.remove("loading"); node.textContent = original; node.removeAttribute("aria-busy"); }
}
function newView() { recommendationRequest?.abort(); return ++viewVersion; }
function details(title, children) {
  const node = element("details"); node.append(element("summary", "", title), ...children); return node;
}
function table(headers, rows) {
  const wrapper = element("div", "table-wrap"); const node = element("table");
  const head = element("thead"); const tr = element("tr"); headers.forEach(text => tr.append(element("th", "", text))); head.append(tr);
  const body = element("tbody"); rows.forEach(values => { const row = element("tr"); values.forEach(value => { const td = element("td"); td.append(value instanceof Node ? value : document.createTextNode(String(value))); row.append(td); }); body.append(row); });
  node.append(head, body); wrapper.append(node); return wrapper;
}
function goalForm(options, target) {
  const form = element("form", "goal-form"); const label = element("label", "", "Карьерная цель"); const select = element("select");
  options.forEach((option, index) => { const item = element("option", "", `${option.role} · ${option.grade}`); item.value = index; item.selected = option.role === target?.role && option.grade === target?.grade; select.append(item); });
  label.append(select); const submit = element("button", "secondary", "Сохранить цель"); submit.type = "submit"; form.append(label, submit);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    try { await withLoading(submit, "Сохраняем…", async () => { await post("/api/employee/goal", options[Number(select.value)]); lastCompletion = null; await showEmployee(); }); }
    catch (error) { showError(pageError, error.message); }
  }); return form;
}
function trajectoryCard(trajectory) {
  const card = element("section", "card"); card.append(element("h2", "", "Карьерная траектория"));
  const now = `${trajectory.employee.role} · ${trajectory.employee.grade}`;
  if (!trajectory.target) { card.append(element("p", "", `${now} → выберите карьерную цель`)); return card; }
  card.append(element("p", "path-line", `${now} → ${trajectory.target.role} · ${trajectory.target.grade}`));
  card.append(element("div", "metric", `${trajectory.coverage_percent}%`), element("p", "muted", `Покрытие требований. Критических навыков с дефицитом: ${trajectory.critical_gaps_remaining}.`));
  const progress = element("div", "progress"); const bar = element("span"); bar.style.width = `${trajectory.coverage_percent}%`; progress.append(bar); card.append(progress);
  card.append(element("p", "mode-note", "Покрытие = сумма уровней, ограниченных требованиями цели, / сумма требуемых уровней. Это не гарантия повышения."));
  const gaps = element("ul", "gap-list");
  trajectory.skill_gaps.forEach(item => {
    const row = element("li", "gap"); const name = element("div"); name.append(element("strong", "", item.skill_name));
    if (item.is_critical) name.append(element("span", "critical", "КРИТИЧЕСКИЙ НАВЫК"));
    row.append(name, element("span", "", `${item.current_level} → ${item.required_level}${item.gap ? ` · осталось ${item.gap}` : " · требование покрыто"}`)); gaps.append(row);
  });
  card.append(details(`Все требования цели (${trajectory.skill_gaps.length})`, [gaps]));
  return card;
}
function progressHistory(trajectory) {
  const card = element("section", "card"); card.append(element("h2", "", "Фактический прогресс"));
  card.append(element("p", "muted", `Оценка: ${trajectory.employee.last_review_date}. Дата демо: ${trajectory.as_of_date}. Учитываются завершённые активности после оценки.`));
  const changes = [...trajectory.applied_skill_changes].reverse();
  if (!changes.length) card.append(element("p", "", "После последней оценки пока нет завершённых активностей."));
  else card.append(details(`Все изменения навыков (${changes.length})`, [table(["Активность", "Дата", "Навык", "Изменение"], changes.map(item => [item.event_title, item.activity_date, item.skill_id, `${item.before_level} → ${item.after_level} (gain ${item.gain}, максимум ${item.max_level})`]))]));
  return card;
}
function recommendationBlock() {
  const card = element("section", "card"); card.append(element("h2", "", "Следующие шаги"));
  const content = element("div"); content.setAttribute("aria-live", "polite"); card.append(content); return { card, content };
}
function renderRecommendations(root, result, employeeMode) {
  root.replaceChildren();
  root.append(element("p", "mode-note", result.mode === "llm" ? `AI выбрал шаги из проверенного списка.${result.cached ? " Использован сохранённый результат." : ""}` : result.fallback_reason || "Рекомендации рассчитаны правилами."));
  if (!result.recommendations.length) root.append(element("p", "muted", "Сейчас нет подходящих шагов. Проверьте цель и доступные активности."));
  const list = element("div", "recommendation-list");
  result.recommendations.forEach(item => {
    const card = element("article", "recommendation"); card.append(element("h3", "", item.title), element("p", "event-meta", `${formats[item.format]} · ${item.duration_hours} ч${item.next_session ? ` · ${item.next_session}` : ""}`));
    const reasons = element("ul", "evidence"); item.evidence.forEach(text => reasons.append(element("li", "", text))); card.append(reasons);
    if (item.selected_reasons.length) card.append(details("Факторы, которые выделил AI", item.selected_reasons.map(text => element("p", "", text))));
    if (item.related_history.length) card.append(details("История по пересекающимся навыкам (до 12 последних записей)", [table(["Дата", "Активность", "Формат", "Статус"], item.related_history.map(row => [row.activity_date, row.title, formats[row.format], statuses[row.status]]))]));
    if (employeeMode) card.append(button("Начать активность", node => startActivity(item, node)));
    list.append(card);
  }); root.append(list);
  const plan = result.plan;
  if (plan?.steps.length) {
    const forecast = element("div", "forecast"); forecast.append(element("h3", "", "Если выполнить выбранные шаги"), element("p", "", `Ожидаемое покрытие: ${plan.coverage_before}% → ${plan.coverage_after}%.`));
    const steps = element("ol"); plan.steps.forEach(step => steps.append(element("li", "", `${step.title} → ${step.coverage_after}%${step.additional_gap_reduction === 0 ? " · без дополнительного сокращения разрыва после предыдущих шагов" : ""}`)));
    forecast.append(steps, element("p", "muted", "Прогноз рассчитан последовательно с учётом gain и max_level. Фактические навыки изменятся после завершения."));
    if (plan.remaining_critical_skills.length) forecast.append(element("p", "", `Останутся критические дефициты: ${plan.remaining_critical_skills.join(", ")}.`));
    root.append(forecast);
  }
}
async function loadRecommendations(root, path, employeeMode, version) {
  recommendationRequest?.abort(); const controller = new AbortController(); recommendationRequest = controller;
  root.replaceChildren(element("p", "loading-message", "Подбираем рекомендации… Профиль уже доступен.")); root.setAttribute("aria-busy", "true");
  try {
    const result = await request(path, { signal: controller.signal });
    if (version !== viewVersion || !root.isConnected) return;
    renderRecommendations(root, result, employeeMode);
    if (result.mode !== "llm") root.append(button("Повторить подбор", () => loadRecommendations(root, path, employeeMode, version), true));
  } catch (error) {
    if (error.name === "AbortError" || version !== viewVersion || !root.isConnected) return;
    root.replaceChildren(element("p", "error", error.message), button("Повторить подбор", () => loadRecommendations(root, path, employeeMode, version)));
  } finally { if (version === viewVersion && recommendationRequest === controller) root.removeAttribute("aria-busy"); }
}
async function showEmployee() {
  const version = newView(); const data = await request("/api/employee/dashboard"); if (version !== viewVersion) return;
  loginView.hidden = true; hrView.hidden = true; employeeView.hidden = false; showError(pageError, "");
  $("#employee-name").textContent = data.trajectory.employee.full_name; $("#user-role").textContent = "Сотрудник";
  employeeDemoMode = data.demo_mode && data.is_demo_user; resetButton.hidden = !employeeDemoMode;
  const root = $("#employee-content"); root.replaceChildren(); root.className = "dashboard";
  if (lastCompletion) {
    const notice = element("section", "success"); notice.setAttribute("role", "status");
    notice.append(element("strong", "", `Активность засчитана: покрытие ${lastCompletion.coverage_before}% → ${lastCompletion.coverage_after}%.`));
    lastCompletion.skill_changes.forEach(item => notice.append(element("p", "", `${item.skill_id}: ${item.before_level} → ${item.after_level}`))); root.append(notice);
  }
  const trajectory = trajectoryCard(data.trajectory); trajectory.append(goalForm(data.goal_options, data.trajectory.target)); root.append(trajectory);
  if (data.active_enrollments.length) {
    const active = element("section", "card"); active.append(element("h2", "", "В процессе"));
    data.active_enrollments.forEach(item => { const row = element("article", "recommendation"); row.append(element("h3", "", item.title), element("p", "event-meta", `${formats[item.format]} · ${item.duration_hours} ч · начато ${item.registered_at}`)); if (employeeDemoMode) row.append(button("Открыть активность", () => openActivityModal(item, item.enrollment_id))); active.append(row); }); root.append(active);
  }
  const rec = recommendationBlock(); root.append(rec.card, progressHistory(data.trajectory));
  void loadRecommendations(rec.content, "/api/employee/recommendations", true, version);
}
function openActivityModal(activity, enrollmentId) {
  $("#activity-modal-title").textContent = activity.title;
  $("#activity-modal-meta").textContent = `${formats[activity.format]} · ${activity.duration_hours} ч`;
  const benefits = $("#activity-modal-benefits"); benefits.replaceChildren();
  (activity.expected_skill_changes || []).forEach(change => benefits.append(element("li", "", `${change.skill_name}: ${change.before_level} → ${change.after_level}`)));
  modalCompleteButton.hidden = !employeeDemoMode;
  modalCompleteButton.onclick = () => completeEnrollment(enrollmentId, modalCompleteButton);
  showError($("#modal-error"), ""); activityModal.showModal();
}
async function startActivity(item, node) {
  try { await withLoading(node, "Начинаем…", async () => { newView(); const result = await post(`/api/employee/activities/${encodeURIComponent(item.event_id)}/enroll`); openActivityModal(item, result.enrollment.enrollment_id); await showEmployee(); }); }
  catch (error) { showError(pageError, error.message); }
}
async function completeEnrollment(id, node) {
  try { await withLoading(node, "Засчитываем…", async () => { newView(); lastCompletion = await post(`/api/employee/enrollments/${encodeURIComponent(id)}/complete`); activityModal.close(); await showEmployee(); }); }
  catch (error) { showError($("#modal-error"), error.message); }
}
async function resetDemo(node) {
  if (!window.confirm("Вернуть вашу демо-цель и прогресс к исходному состоянию? Созданные через приложение активности будут удалены.")) return;
  try { await withLoading(node, "Сбрасываем…", async () => { newView(); await post("/api/employee/demo-reset"); lastCompletion = null; await showEmployee(); }); }
  catch (error) { showError(pageError, error.message); }
}
function historyTable(history) {
  return table(["Дата", "Активность", "Участие", "Статус", "Выполнено"], history.map(row => [row.activity_date, row.title, row.mandatory ? "Обязательная" : "Добровольная", statuses[row.status], `${row.completion_pct}%`]));
}
async function showHrDetail(id, node) {
  const action = async () => {
    const version = newView();
    try {
      const detail = await request(`/api/hr/employees/${encodeURIComponent(id)}`); if (version !== viewVersion) return;
      const root = $("#hr-content"); root.replaceChildren(); root.className = "dashboard"; showError(hrError, "");
      root.append(button("Вернуться к обзору", button => withLoading(button, "Загружаем…", () => showHr()), true));
      const heading = element("section", "card"); heading.append(element("h2", "", detail.employee.full_name), element("p", "muted", `${id} · ${detail.employee.department}`)); root.append(heading, trajectoryCard(detail.trajectory));
      const rec = recommendationBlock(); root.append(rec.card);
      const history = element("section", "card"); history.append(element("h2", "", "История участия"), element("p", "muted", "Исходные записи для проверки сигналов поддержки. Обязательные активности не входят в метрики добровольного участия."), historyTable(detail.history)); root.append(history);
      void loadRecommendations(rec.content, `/api/hr/employees/${encodeURIComponent(id)}/recommendations`, false, version);
    } catch (error) { if (version === viewVersion) showError(hrError, error.message); }
  };
  return node ? withLoading(node, "Загружаем…", action) : action();
}
function importedProfiles(result, interactive) {
  const list = element("div", "import-result"); list.append(element("p", "", `Новых профилей: ${result.employees_imported}; записей истории: ${result.history_records_imported}. Уже существуют без изменений: ${result.employees_skipped} профилей, ${result.history_records_skipped} записей.`));
  result.profiles.forEach(profile => { const text = `${profile.full_name} (${profile.employee_id}) · ${profile.role} · ${profile.grade}`; list.append(interactive ? button(text, node => showHrDetail(profile.employee_id, node), true) : element("p", "", text)); }); return list;
}
function importForm() {
  const card = element("section", "card"); card.append(element("h2", "", "Загрузить проверочные данные"), element("p", "muted", "Сначала проверьте JSON/CSV в схеме датасета. Проверка не сохраняет данные. При импорте весь пакет проверяется повторно."));
  const form = element("form", "upload");
  const employeeInput = element("input"); employeeInput.type = "file"; employeeInput.accept = ".json,application/json"; employeeInput.required = true;
  const historyInput = element("input"); historyInput.type = "file"; historyInput.accept = ".csv,text/csv"; historyInput.required = true;
  const jsonLabel = element("label", "", "employees.json"); jsonLabel.append(employeeInput); const csvLabel = element("label", "", "activity_history.csv"); csvLabel.append(historyInput);
  const submit = element("button", "", "Проверить пакет"); submit.type = "submit"; const preview = element("div"); preview.setAttribute("aria-live", "polite");
  let uploadVersion = 0;
  const clear = () => { uploadVersion += 1; preview.replaceChildren(); }; employeeInput.addEventListener("change", clear); historyInput.addEventListener("change", clear);
  form.append(jsonLabel, csvLabel, submit, preview);
  form.addEventListener("submit", async event => {
    event.preventDefault(); clear(); const version = uploadVersion;
    try { await withLoading(submit, "Проверяем…", async () => {
      const payload = { employees_json: await employeeInput.files[0].text(), history_csv: await historyInput.files[0].text() };
      const result = await post("/api/hr/import/preview", payload); if (!form.isConnected || version !== uploadVersion) return;
      showError(hrError, ""); preview.append(importedProfiles(result, false));
      preview.append(button("Подтвердить импорт", async node => {
        try { await withLoading(node, "Импортируем…", async () => { lastImport = await post("/api/hr/import", payload); if (form.isConnected) await showHr(new URLSearchParams()); }); }
        catch (error) { showError(hrError, error.message); }
      }));
    }); } catch (error) { showError(hrError, error.message); }
  }); card.append(form); return card;
}
function selectFilter(label, name, values, selected) {
  const wrapper = element("label", "", label); const select = element("select"); select.name = name;
  const all = element("option", "", "Все"); all.value = ""; select.append(all);
  values.forEach(value => { const option = element("option", "", value); option.value = value; option.selected = value === selected; select.append(option); }); wrapper.append(select); return wrapper;
}
function renderHrDashboard(data) {
  const root = $("#hr-content"); root.replaceChildren(); root.className = "dashboard";
  if (lastImport) { const card = element("section", "card"); card.append(element("h2", "", "Последний импорт в этой сессии"), importedProfiles(lastImport, true)); root.append(card); }
  const filters = element("form", "filters");
  filters.append(selectFilter("Подразделение", "department", data.filter_options.departments, data.filters.department), selectFilter("Роль", "role", data.filter_options.roles, data.filters.role), selectFilter("Грейд", "grade", data.filter_options.grades, data.filters.grade));
  const apply = element("button", "", "Применить"); apply.type = "submit"; filters.append(apply);
  filters.addEventListener("submit", event => { event.preventDefault(); const params = new URLSearchParams(new FormData(filters)); [...params.keys()].forEach(key => !params.get(key) && params.delete(key)); void withLoading(apply, "Загружаем…", () => showHr(params)); }); root.append(filters);
  const stats = element("div", "stat-grid"); [["Сотрудников", data.summary.employees], ["Нужна поддержка", data.summary.needs_support], ["Компетенций с разрывами", data.summary.competencies_with_gaps]].forEach(([label, value]) => { const item = element("div", "stat"); item.append(element("strong", "", value), element("span", "muted", label)); stats.append(item); }); root.append(stats);
  if (data.invalid_profiles.length) root.append(element("p", "error", `Не удалось рассчитать профили: ${data.invalid_profiles.map(item => item.employee_id).join(", ")}. Проверьте их карьерные цели.`));
  const departments = element("section", "card"); departments.append(element("h2", "", "Критические дефициты по подразделениям"), element("p", "muted", "Доля сотрудников выбранной группы хотя бы с одним критическим дефицитом. Нажмите на подразделение, чтобы открыть его срез."), table(["Подразделение", "Сотрудников", "С критическим дефицитом", "Доля"], data.department_gaps.map(item => [button(item.department, node => withLoading(node, "Загружаем…", () => { const params = new URLSearchParams(hrFilters); params.set("department", item.department); return showHr(params); }), true), item.employees, item.with_critical_gaps, `${item.critical_gap_percent}%`]))); root.append(departments);
  const trend = element("section", "card"); trend.append(element("h2", "", "Добровольное участие за 12 месяцев"), element("p", "muted", `Срез на ${data.as_of_date}; последний месяц может быть неполным. Доля = завершённые / (завершённые + отказы, пропуски, незавершённые и просроченные). В процессе — отдельно. Месяц определяется датой записи в датасете.`), table(["Месяц", "Завершено", "Не завершено", "В процессе", "Доля завершённых"], data.participation_trend.map(item => { const bar = element("div", "trend-cell"); const fill = element("span", "trend-fill"); fill.style.width = `${item.completion_percent || 0}%`; bar.append(fill, element("span", "trend-value", item.completion_percent === null ? "Нет данных" : `${item.completion_percent}%`)); return [item.month, item.completed, item.noncompletion, item.in_progress, bar]; }))); root.append(trend);
  const competency = element("section", "card"); competency.append(element("h2", "", "Проседающие компетенции"), element("p", "muted", "Разрывы карьерных целей выбранной группы."), details(`Все компетенции с дефицитами (${data.competency_gaps.length})`, [table(["Навык", "Сотрудников", "Суммарный разрыв", "Критический у"], data.competency_gaps.map(item => [item.skill_name, item.employees_affected, item.total_gap, item.critical_gap_count]))])); root.append(competency);
  const people = element("section", "card"); people.append(element("h2", "", "Сигналы поддержки"), element("p", "muted", `Период: ${data.support_period_start} — ${data.as_of_date}. Сигналы помогают предложить поддержку. Откройте сотрудника, чтобы проверить историю участия.`), table(["Сотрудник", "Роль", "Покрытие", "Сигналы"], data.employees.map(person => [button(person.full_name, node => showHrDetail(person.employee_id, node), true), `${person.role} · ${person.grade}`, person.coverage_percent === null ? "Цель не задана" : `${person.coverage_percent}%`, person.support_signals.join(" ") || "Нет"]))); root.append(people, importForm());
}
async function showHr(params = hrFilters) {
  const version = newView(); hrFilters = new URLSearchParams(params);
  try { const suffix = params.toString(); const data = await request(`/api/hr/dashboard${suffix ? `?${suffix}` : ""}`); if (version !== viewVersion) return; loginView.hidden = true; employeeView.hidden = true; hrView.hidden = false; showError(hrError, ""); renderHrDashboard(data); }
  catch (error) { if (version === viewVersion) showError(hrView.hidden ? loginError : hrError, error.message); }
}
async function restoreSession() {
  try { const user = await request("/api/me"); if (user.access_role === "hr") await showHr(); else await showEmployee(); }
  catch (_) { loginView.hidden = false; employeeView.hidden = true; hrView.hidden = true; }
}
$("#login-form").addEventListener("submit", async event => {
  event.preventDefault(); showError(loginError, ""); const form = new FormData(event.currentTarget);
  try { await withLoading(event.currentTarget.querySelector("button[type=submit]"), "Входим…", async () => { const user = await post("/api/login", { username: form.get("username"), password: form.get("password") }); if (user.access_role === "hr") await showHr(); else await showEmployee(); }); }
  catch (error) { showError(loginError, error.message); }
});
async function logout(node) {
  try { await withLoading(node, "Выходим…", async () => { newView(); await post("/api/logout"); window.location.reload(); }); }
  catch (error) { showError(employeeView.hidden ? hrError : pageError, error.message); }
}
$("#logout-button").addEventListener("click", event => logout(event.currentTarget));
$("#hr-logout-button").addEventListener("click", event => logout(event.currentTarget));
resetButton.addEventListener("click", () => resetDemo(resetButton));
void restoreSession();
