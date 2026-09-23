const loginView = document.querySelector("#login-view");
const employeeView = document.querySelector("#employee-view");
const hrView = document.querySelector("#hr-view");
const loginError = document.querySelector("#login-error");
const pageError = document.querySelector("#page-error");

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

function renderDashboard(data) {
  const { trajectory, recommendations, recommendation_mode: mode, recommendation_notice: notice, active_enrollments: activeEnrollments, demo_mode: demoMode } = data;
  document.querySelector("#employee-name").textContent = trajectory.employee.full_name;
  document.querySelector("#user-role").textContent = "Сотрудник";
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
  if (mode === "rules_fallback") recommendationsCard.append(element("p", "mode-note", "Рекомендации построены проверяемыми правилами. Полный AI-режим подключается через конфигурацию модели."));
  if (notice && mode !== "rules_fallback") recommendationsCard.append(element("p", "mode-note", notice));
  const recommendationList = element("div", "recommendation-list");
  if (!recommendations.length) recommendationList.append(element("p", "muted", "Сейчас нет доступных добровольных активностей, которые сокращают текущие разрывы."));
  recommendations.forEach(item => {
    const card = element("article", "recommendation");
    card.append(element("h3", "", item.title), element("p", "event-meta", `${item.format} · ${item.duration_hours} ч${item.next_session ? ` · ближайшая сессия ${item.next_session}` : " · доступно в своём темпе"}`));
    const evidence = element("ul", "evidence"); item.evidence.forEach(reason => evidence.append(element("li", "", reason))); card.append(evidence);
    const start = element("button", "", "Начать активность");
    start.addEventListener("click", () => enroll(item.event_id)); card.append(start); recommendationList.append(card);
  }); recommendationsCard.append(recommendationList); dashboard.append(recommendationsCard); root.append(dashboard);

  if (activeEnrollments.length) {
    const active = element("section", "card"); active.append(element("h2", "", "В процессе"));
    activeEnrollments.forEach(item => {
      const row = element("article", "recommendation"); row.append(element("h3", "", item.title), element("p", "event-meta", `${item.format} · ${item.duration_hours} ч · начато ${item.registered_at}`));
      if (demoMode) { const complete = element("button", "", "Завершить в демо"); complete.addEventListener("click", () => completeEnrollment(item.enrollment_id)); row.append(complete); }
      active.append(row);
    }); dashboard.append(active);
  }
}

async function showEmployee() {
  const data = await request("/api/employee/dashboard");
  loginView.hidden = true; hrView.hidden = true; employeeView.hidden = false; showError(pageError, ""); renderDashboard(data);
}

async function enroll(eventId) {
  try { await request(`/api/employee/activities/${encodeURIComponent(eventId)}/enroll`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); await showEmployee(); }
  catch (error) { showError(pageError, error.message); }
}

async function completeEnrollment(enrollmentId) {
  try { await request(`/api/employee/enrollments/${encodeURIComponent(enrollmentId)}/complete`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); await showEmployee(); }
  catch (error) { showError(pageError, error.message); }
}

async function restoreSession() {
  try {
    const user = await request("/api/me");
    if (user.access_role === "hr") { loginView.hidden = true; employeeView.hidden = true; hrView.hidden = false; return; }
    await showEmployee();
  } catch (_) { loginView.hidden = false; employeeView.hidden = true; hrView.hidden = true; }
}

document.querySelector("#login-form").addEventListener("submit", async event => {
  event.preventDefault(); showError(loginError, "");
  const form = new FormData(event.currentTarget);
  try {
    const user = await request("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: form.get("username"), password: form.get("password") }) });
    if (user.access_role === "hr") { loginView.hidden = true; hrView.hidden = false; return; }
    await showEmployee();
  } catch (error) { showError(loginError, error.message); }
});

async function logout() { await request("/api/logout", { method: "POST" }); window.location.reload(); }
document.querySelector("#logout-button").addEventListener("click", logout);
document.querySelector("#hr-logout-button").addEventListener("click", logout);
restoreSession();
