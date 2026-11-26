"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="/static/icons.svg#${name}"></use></svg>`;
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);
const tripId = document.body.dataset.holidayId;
const tripURL = `/api/holidays/${tripId}`;
const categories = ["Clothing", "Medication & Health", "Documents & Tech", "Toiletries", "Miscellaneous"];
const categoryIcons = ["bag", "heart", "template", "sun", "grid"];
let holidays = [];
let trip = null;
let templates = [];
let packingFilter = "all";
let aiBusy = false;
let statusBusy = false;
let dashboardLoaded = false;

function preference(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (error) {
    console.warn("Browser preferences cannot be saved.", error.name);
  }
  return null;
}

function todayKey() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

const parseDate = (value) => new Date(`${value}T00:00:00Z`);
const dateKey = (value) => value.toISOString().slice(0, 10);
const daysBetween = (from, to) => Math.round((parseDate(to) - parseDate(from)) / 86400000);
const formatDate = (value, options = {}) => parseDate(value).toLocaleDateString(undefined, {
  day: "numeric", month: "short", ...options, timeZone: "UTC",
});
const dateRange = (holiday) => `${formatDate(holiday.start_date)} - ${formatDate(holiday.end_date, { year: "numeric" })}`;
const percent = (packed, total) => total ? Math.round(packed / total * 100) : 0;
let calendarMonth = parseDate(todayKey());
calendarMonth.setUTCDate(1);
let currentView = preference("away-view") === "calendar" ? "calendar" : "list";

function tripStatus(holiday) {
  const today = todayKey();
  if (holiday.end_date < today) return { key: "past", label: "Memories made", short: "Past" };
  if (holiday.start_date <= today) return { key: "active", label: "Away right now", short: "Active" };
  const days = daysBetween(today, holiday.start_date);
  return { key: "upcoming", label: days === 1 ? "Tomorrow!" : `In ${days} days`, short: "Upcoming" };
}

function money(value) {
  return new Intl.NumberFormat(undefined, {
    style: "currency", currency: trip?.currency || "USD", minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(value);
}

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}

async function api(url, { method = "GET", data, timeout = 15000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {
      method,
      headers: {
        Accept: "application/json",
        ...(method !== "GET" ? { "Content-Type": "application/json", "X-Requested-With": "HolidayPlanner" } : {}),
      },
      ...(method !== "GET" ? { body: JSON.stringify(data ?? {}) } : {}),
      signal: controller.signal,
    });
    if (response.status === 204) return null;
    let result;
    try {
      result = await response.json();
    } catch {
      throw new Error(`The server returned an unreadable response (HTTP ${response.status}).`);
    }
    if (!response.ok) throw new Error(result.error || `Request failed (HTTP ${response.status}).`);
    return result;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("The request timed out. Refresh to check for saved changes before retrying.");
    if (error instanceof TypeError) throw new Error("Cannot reach your planner server. Check your connection and try again.");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function toast(message, isError = false) {
  const region = $("#toast-region");
  if ("showPopover" in region && !region.hasAttribute("popover")) region.setAttribute("popover", "manual");
  const element = document.createElement("div");
  element.className = `toast${isError ? " error" : ""}`;
  element.innerHTML = `<span>${escapeHTML(message)}</span><button type="button" class="icon-button" aria-label="Dismiss notification">${icon("close")}</button>`;
  if (isError) element.setAttribute("role", "alert");
  const remove = () => {
    element.remove();
    if (!region.children.length && region.matches(":popover-open")) region.hidePopover();
  };
  $("button", element).addEventListener("click", remove);
  region.append(element);
  if ("showPopover" in region) region.showPopover();
  setTimeout(remove, isError ? 12000 : 5000);
}

async function safely(callback) {
  try {
    await callback();
  } catch (error) {
    toast(error.message, true);
  }
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const button = $("#theme-toggle");
  button.innerHTML = icon(theme === "dark" ? "sun" : "moon");
  button.setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} mode`);
}

setTheme(preference("away-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
$("#theme-toggle").addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  setTheme(theme);
  preference("away-theme", theme);
});

async function checkAI(showMessage = false) {
  if (statusBusy) return;
  statusBusy = true;
  const badge = $("#ai-status");
  badge.disabled = true;
  try {
    const status = await api("/api/ai/status", { timeout: 10000 });
    badge.className = `status-badge ${status.online ? "online" : "offline"}`;
    badge.innerHTML = `<span class="status-dot"></span><span>AI: ${status.online ? "Online" : "Offline"}</span>`;
    badge.title = status.message + (status.model ? ` (${status.model})` : "");
    if (showMessage) toast(badge.title, !status.online);
  } catch (error) {
    badge.className = "status-badge offline";
    badge.innerHTML = '<span class="status-dot"></span><span>AI: Offline</span>';
    badge.title = error.message;
    if (showMessage) toast(error.message, true);
  } finally {
    badge.disabled = false;
    statusBusy = false;
  }
}
$("#ai-status").addEventListener("click", () => checkAI(true));

function confirmDelete(title, message) {
  return new Promise((resolve) => {
    const dialog = $("#confirm-dialog");
    setText("#confirm-title", title);
    setText("#confirm-message", message);
    dialog.returnValue = "";
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
    dialog.showModal();
  });
}

function openForm(kind, values = {}, id = null) {
  const form = $(`#${kind}-form`);
  form.reset();
  form.dataset.recordId = id || "";
  const error = $(".form-error", form);
  if (error) error.hidden = true;
  for (const [key, value] of Object.entries(values)) {
    const input = form.elements.namedItem(key);
    if (!input) continue;
    if (input.type === "checkbox") input.checked = Boolean(value);
    else input.value = value ?? "";
  }
  const titles = {
    holiday: id ? "Edit holiday" : "New holiday",
    packing: id ? "Edit packing item" : "Add packing item",
    flight: id ? "Edit flight" : "Add flight",
    expense: id ? "Edit expense" : "Log an expense",
  };
  setText(`#${kind}-form-title`, titles[kind]);
  if (kind === "holiday") {
    setText("#holiday-save-label", id ? "Save changes" : "Create holiday");
    form.elements.end_date.min = form.elements.start_date.value || "";
  }
  if (kind === "expense") setText("#expense-amount-label", `Amount (${trip.currency})`);
  $(`#${kind}-dialog`).showModal();
}

function formData(form, kind) {
  const data = Object.fromEntries(new FormData(form));
  if (kind === "holiday") {
    data.laundry_available = data.laundry_available === "true";
    data.budget = data.budget || "0";
    data.currency = data.currency.toUpperCase();
  }
  if (kind === "packing") {
    data.quantity = Number(data.quantity);
    data.packed = form.elements.packed.checked;
  }
  return data;
}

async function submitForm(event, kind) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  if (button.disabled) return;
  const errorBox = $(".form-error", form);
  errorBox.hidden = true;
  button.disabled = true;
  const id = form.dataset.recordId;
  const collections = { packing: "packing", flight: "flights", expense: "expenses" };
  const url = kind === "holiday" ? `/api/holidays${id ? `/${id}` : ""}` :
    `${tripURL}/${collections[kind]}${id ? `/${id}` : ""}`;
  try {
    const result = await api(url, { method: id ? "PATCH" : "POST", data: formData(form, kind) });
    $(`#${kind}-dialog`).close();
    if (kind === "holiday" && !id) {
      location.assign(`/holidays/${result.id}`);
      return;
    }
    await loadTrip();
    toast("Saved. One less thing to think about.");
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
    if (!$(`#${kind}-dialog`).open) toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

for (const kind of ["holiday", "packing", "flight", "expense"]) {
  $(`#${kind}-form`)?.addEventListener("submit", (event) => submitForm(event, kind));
}
$("#holiday-form").elements.start_date.addEventListener("change", (event) => {
  const end = $("#holiday-form").elements.end_date;
  end.min = event.target.value;
  if (!end.value || end.value < event.target.value) end.value = event.target.value;
});

function filteredHolidays() {
  const search = $("#holiday-search").value.trim().toLocaleLowerCase();
  return holidays.filter((holiday) => `${holiday.title} ${holiday.destination}`.toLocaleLowerCase().includes(search));
}

function cardHTML(holiday, index) {
  const status = tripStatus(holiday);
  const packed = percent(holiday.packed_count, holiday.item_count);
  return `<a href="/holidays/${holiday.id}" class="holiday-card">
    <div class="card-cover ${["", "mint", "lavender"][index % 3]}"><span class="cover-icon">${icon("plane")}</span><span class="pill ${status.key}">${icon(status.key === "active" ? "sun" : "clock")}${escapeHTML(status.label)}</span></div>
    <div class="card-body"><h3>${escapeHTML(holiday.title)}</h3><p class="card-destination">${icon("pin")}${escapeHTML(holiday.destination)}</p>
    <p class="card-dates">${icon("calendar")}${escapeHTML(dateRange(holiday))} &middot; ${daysBetween(holiday.start_date, holiday.end_date) + 1} days</p>
    <div class="card-packing"><div><span>${icon("bag")}${holiday.packed_count}/${holiday.item_count} items packed</span><span>${packed}%</span></div><progress value="${packed}" max="100" aria-label="${escapeHTML(holiday.title)} packing completion"></progress></div></div></a>`;
}

function renderDashboard() {
  const filtered = filteredHolidays();
  const upcoming = holidays.filter((holiday) => tripStatus(holiday).key === "upcoming");
  const live = holidays.filter((holiday) => tripStatus(holiday).key !== "past");
  const packed = live.reduce((total, holiday) => total + holiday.packed_count, 0);
  const count = live.reduce((total, holiday) => total + holiday.item_count, 0);
  setText("#stat-upcoming", upcoming.length);
  setText("#stat-next", upcoming[0]?.destination || "Ready when you are");
  setText("#stat-next-caption", upcoming[0] ? `${tripStatus(upcoming[0]).label} - ${formatDate(upcoming[0].start_date)}` : "Something to look forward to");
  setText("#stat-progress", `${percent(packed, count)}%`);
  setText("#stat-packed-caption", count ? `${packed} of ${count} items ready to go` : "for active & upcoming holidays");
  setText("#holiday-count", filtered.length);
  const list = $("#holiday-list");
  if (!holidays.length) {
    list.innerHTML = `<div class="empty-state"><span class="stat-icon blue">${icon("bag")}</span><h3>Your suitcase is a blank canvas.</h3><p>A weekend away or a once-in-a-lifetime escape. Give your next adventure a place to begin.</p><button type="button" class="button primary" data-action="new-holiday">${icon("plus")}Plan your first holiday</button></div>`;
  } else if (!filtered.length) {
    list.innerHTML = `<div class="empty-state"><span class="stat-icon blue">${icon("search")}</span><h3>No holidays found</h3><p>Try a different trip title or destination.</p></div>`;
  } else {
    list.innerHTML = ["active", "upcoming", "past"].map((key) => {
      const group = filtered.filter((holiday) => tripStatus(holiday).key === key);
      if (key === "past") group.reverse();
      return group.length ? `<section class="trip-group"><h3 class="group-heading">${{ active: "Away right now", upcoming: "Upcoming adventures", past: "Past holidays" }[key]} <span>${group.length}</span></h3><div class="holiday-cards">${group.map(cardHTML).join("")}</div></section>` : "";
    }).join("");
  }
  renderCalendar(filtered);
  setDashboardView(currentView);
}

function setDashboardView(view) {
  currentView = view;
  $("#holiday-list").hidden = view !== "list";
  $("#calendar-view").hidden = view !== "calendar";
  $("#list-view-button").setAttribute("aria-pressed", String(view === "list"));
  $("#calendar-view-button").setAttribute("aria-pressed", String(view === "calendar"));
  preference("away-view", view);
}

function renderCalendar(filtered) {
  setText("#calendar-title", calendarMonth.toLocaleDateString(undefined, { month: "long", year: "numeric", timeZone: "UTC" }));
  const start = new Date(calendarMonth);
  start.setUTCDate(1 - (start.getUTCDay() + 6) % 7);
  const grid = $("#calendar-grid");
  grid.replaceChildren();
  for (let week = 0; week < 6; week++) {
    const weekStart = new Date(start);
    weekStart.setUTCDate(start.getUTCDate() + week * 7);
    const weekEnd = new Date(weekStart);
    weekEnd.setUTCDate(weekStart.getUTCDate() + 6);
    const weekElement = document.createElement("div");
    weekElement.className = "calendar-week";
    const days = document.createElement("div");
    days.className = "calendar-days";
    for (let day = 0; day < 7; day++) {
      const date = new Date(weekStart);
      date.setUTCDate(weekStart.getUTCDate() + day);
      const key = dateKey(date);
      const cell = document.createElement("div");
      cell.className = `day-cell${date.getUTCMonth() !== calendarMonth.getUTCMonth() ? " outside" : ""}${key === todayKey() ? " today" : ""}`;
      cell.innerHTML = `<button type="button" data-action="new-holiday" data-date="${key}" aria-label="New holiday on ${escapeHTML(formatDate(key, { month: "long", year: "numeric" }))}">${date.getUTCDate()}</button>`;
      days.append(cell);
    }
    const events = document.createElement("div");
    events.className = "calendar-events";
    const lanes = [];
    for (const holiday of filtered) {
      if (holiday.start_date > dateKey(weekEnd) || holiday.end_date < dateKey(weekStart)) continue;
      const first = Math.max(0, daysBetween(dateKey(weekStart), holiday.start_date));
      const last = Math.min(6, daysBetween(dateKey(weekStart), holiday.end_date));
      let lane = lanes.findIndex((end) => end < first);
      if (lane === -1) lane = lanes.length;
      lanes[lane] = last;
      const event = document.createElement("a");
      event.className = `calendar-event ${tripStatus(holiday).key}`;
      event.href = `/holidays/${holiday.id}`;
      event.textContent = holiday.title;
      event.title = `${holiday.title} | ${holiday.destination} | ${dateRange(holiday)}`;
      event.style.gridColumn = `${first + 1} / ${last + 2}`;
      event.style.gridRow = String(lane + 1);
      events.append(event);
    }
    weekElement.append(days, events);
    grid.append(weekElement);
  }
}

async function loadDashboard() {
  const errorBox = $("#dashboard-error");
  try {
    holidays = await api("/api/holidays");
    dashboardLoaded = true;
    errorBox.hidden = true;
    renderDashboard();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
    $("#holiday-list").innerHTML = '<div class="empty-inline"><button type="button" class="button secondary" data-action="refresh">Try again</button></div>';
  }
}

function recordActions(kind, id, label) {
  return `<div class="row-actions no-print"><button type="button" class="icon-button" data-action="edit-${kind}" data-id="${id}" aria-label="Edit ${escapeHTML(label)}">${icon("edit")}</button><button type="button" class="icon-button" data-action="delete-${kind}" data-id="${id}" aria-label="Delete ${escapeHTML(label)}">${icon("trash")}</button></div>`;
}

function renderPacking() {
  const packed = percent(trip.packed_count, trip.item_count);
  setText("#packing-count", `${trip.packed_count} of ${trip.item_count} items packed`);
  setText("#packing-percent", `${packed}%`);
  $("#packing-progress").value = packed;
  const list = $("#packing-list");
  if (!trip.packing_items.length) {
    list.innerHTML = `<div class="empty-inline">${icon("bag")}A little preparation goes a long way.<br>Add your first item, load a template, or try Smart pack.</div>`;
    return;
  }
  let visibleCount = 0;
  list.innerHTML = categories.map((category, index) => {
    const items = trip.packing_items.filter((item) => item.category === category);
    if (!items.length) return "";
    const visible = items.filter((item) => packingFilter === "all" || item.packed === (packingFilter === "packed"));
    visibleCount += visible.length;
    return `<section class="packing-category${visible.length ? "" : " filtered-out"}"><h3>${icon(categoryIcons[index])}${escapeHTML(category)}<small>${items.filter((item) => item.packed).length}/${items.length}</small></h3>${items.map((item) => {
      const hidden = packingFilter !== "all" && item.packed !== (packingFilter === "packed");
      return `<div class="packing-row${item.packed ? " is-packed" : ""}${hidden ? " filtered-out" : ""}"><label><input type="checkbox" data-packing-id="${item.id}"${item.packed ? " checked" : ""}><span class="item-name">${escapeHTML(item.name)}</span></label><span class="quantity-tag">x${item.quantity}</span>${recordActions("packing", item.id, item.name)}</div>`;
    }).join("")}</section>`;
  }).join("");
  if (!visibleCount) list.insertAdjacentHTML("beforeend", `<p class="empty-inline no-print">${packingFilter === "packed" ? "Nothing packed yet. Your first checkmark is waiting." : "All packed. You are good to go!"}</p>`);
}

function flightTime(value) {
  if (!value) return "Time not added";
  const [day, time] = value.split("T");
  return `${formatDate(day, { year: "numeric" })} - ${time}`;
}

function renderFlights() {
  $("#flight-list").innerHTML = trip.flights.length ? trip.flights.map((flight) => `
    <article class="flight-card"><div class="flight-card-header"><div><strong>${escapeHTML(flight.flight_number)}</strong><span>${escapeHTML(flight.airline)}</span></div>${recordActions("flight", flight.id, flight.flight_number)}</div>
    <div class="flight-route"><div><div class="flight-airport">${escapeHTML(flight.departure_airport || "Departure TBD")}</div><p class="flight-time">${escapeHTML(flightTime(flight.departure_time))}</p><span class="flight-zone">${escapeHTML(flight.departure_timezone || "Local time")}</span></div><div class="route-line">${icon("plane")}</div><div class="arrival"><div class="flight-airport">${escapeHTML(flight.arrival_airport || "Arrival TBD")}</div><p class="flight-time">${escapeHTML(flightTime(flight.arrival_time))}</p><span class="flight-zone">${escapeHTML(flight.arrival_timezone || "Local time")}</span></div></div>
    <div class="flight-extra"><span>Terminal <strong>${escapeHTML(flight.terminal || "Not added")}</strong></span><span>Gate <strong>${escapeHTML(flight.gate || "Not added")}</strong></span><span>Booking <strong>${escapeHTML(flight.booking_code || "Not added")}</strong></span></div></article>`).join("") :
    `<div class="empty-inline">${icon("plane")}From here to somewhere wonderful.<br>Add your flights to keep every connection in one place.</div>`;
}

function renderBudget() {
  const spentPercent = trip.budget ? Math.round(trip.spent / trip.budget * 100) : 0;
  setText("#budget-remaining", money(trip.remaining));
  $("#budget-remaining").classList.toggle("over-budget", trip.remaining < 0);
  setText("#budget-caption", trip.remaining < 0 ? "Over budget" : "Remaining budget");
  setText("#budget-total", `of ${money(trip.budget)} total budget`);
  setText("#budget-spent", money(trip.spent));
  setText("#budget-percent", trip.budget ? `${spentPercent}% used` : "No budget set");
  $("#budget-progress").value = Math.min(100, spentPercent);
  setText("#expense-count", trip.expenses.length);
  setText("#expense-currency-note", `All expenses are in ${trip.currency}. No currency conversion is applied.`);
  $("#expense-list").innerHTML = trip.expenses.length ? trip.expenses.map((expense) => `
    <div class="expense-row"><div class="expense-info"><strong>${escapeHTML(expense.description)}</strong><small>${escapeHTML(expense.category)} &middot; ${escapeHTML(formatDate(expense.date, { year: "numeric" }))}</small></div><div class="expense-value"><strong>${escapeHTML(money(expense.amount))}</strong>${recordActions("expense", expense.id, expense.description)}</div></div>`).join("") :
    '<p class="empty-inline">A fresh start for your travel budget.<br>No expenses logged yet.</p>';
}

function renderTrip() {
  document.title = `${trip.title} | Away Holiday Planner`;
  const status = tripStatus(trip);
  setText("#trip-title", trip.title);
  setText("#trip-destination", trip.destination);
  setText("#trip-dates", dateRange(trip));
  setText("#trip-duration", `${trip.duration} ${trip.duration === 1 ? "day" : "days"}`);
  setText("#trip-status", status.label);
  $("#trip-status").className = `pill ${status.key}`;
  setText("#accommodation-name", trip.accommodation_name || "A home base, still to be found");
  setText("#accommodation-address", trip.accommodation_address || "No address added");
  setText("#booking-references", trip.booking_references || "No booking references added");
  setText("#trip-notes", trip.notes || "A blank page for your travel ideas.");
  setText("#trip-weather", trip.weather);
  setText("#trip-laundry", trip.laundry_available ? "Yes - wash & rewear" : "No");
  setText("#trip-air-quality", trip.air_quality);
  $("#trip-air-quality").classList.toggle("danger-text", trip.air_quality === "High/Unhealthy");
  setText("#trip-dietary", trip.dietary_requirements || "None noted");
  renderPacking();
  renderFlights();
  renderBudget();
}

async function loadTrip() {
  try {
    trip = await api(tripURL);
    $("#trip-error").hidden = true;
    renderTrip();
  } catch (error) {
    $("#trip-error").textContent = error.message;
    $("#trip-error").hidden = false;
    throw error;
  }
}

async function showTemplates() {
  const dialog = $("#templates-dialog");
  if (!dialog.open) dialog.showModal();
  $("#template-list").innerHTML = '<p class="loading-message">Loading your templates...</p>';
  try {
    templates = await api("/api/templates");
    renderTemplates();
  } catch (error) {
    $("#template-list").innerHTML = `<p class="form-error">${escapeHTML(error.message)}</p>`;
  }
}

function renderTemplates() {
  $("#template-list").innerHTML = templates.length ? templates.map((template) => `<div class="template-row"><div><strong>${escapeHTML(template.name)}</strong><small>${template.item_count} items &middot; starts unpacked</small></div><div>${tripId ? `<button type="button" class="button secondary small" data-action="apply-template" data-id="${template.id}">Load</button>` : ""}<button type="button" class="icon-button" data-action="delete-template" data-id="${template.id}" aria-label="Delete ${escapeHTML(template.name)} template">${icon("trash")}</button></div></div>`).join("") :
    '<div class="empty-inline">No templates yet. Save a holiday packing list here and make next time easier.</div>';
  if (tripId) setText("#templates-help", "Load a template to add missing items. Existing items, quantities, and checkmarks are kept.");
}

$("#template-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  if (button.disabled) return;
  button.disabled = true;
  const errorBox = $(".form-error", form);
  errorBox.hidden = true;
  try {
    const result = await api(`${tripURL}/templates`, { method: "POST", data: { name: form.elements.name.value } });
    templates = result.templates;
    renderTemplates();
    form.reset();
    toast("Packing template saved for your next adventure.");
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
  }
});

function appendChat(role, content, isError = false) {
  const message = document.createElement("article");
  message.className = `chat-message ${role}${isError ? " error" : ""}`;
  message.innerHTML = `<span class="message-label">${role === "user" ? "You" : "Trip companion"}</span><div class="message-body"></div>`;
  $(".message-body", message).textContent = content;
  $("#chat-messages").append(message);
  $("#chat-messages").scrollTop = $("#chat-messages").scrollHeight;
}

function renderChat(messages) {
  const container = $("#chat-messages");
  container.replaceChildren();
  if (!messages.length) {
    container.innerHTML = `<div class="chat-welcome">${icon("sparkles")}<h3>Consider me your packing partner.</h3><p>I can build your packing list, add flights, log expenses, and help spot the things you might have missed.<br><br>Try: "Log 140 for a hotel deposit under Accommodation."</p></div>`;
  } else {
    for (const message of messages) appendChat(message.role, message.content);
  }
}

async function openAI() {
  const dialog = $("#ai-dialog");
  if (dialog.open) return;
  dialog.showModal();
  if (aiBusy) return;
  try {
    renderChat(await api(`${tripURL}/chat`));
  } catch (error) {
    renderChat([]);
    appendChat("assistant", error.message, true);
  }
}

function setAIBusy(busy) {
  aiBusy = busy;
  $("#ai-working").hidden = !busy;
  $$('[data-action="generate-packing"], [data-action="audit"], #chat-form button, #chat-input').forEach((button) => { button.disabled = busy; });
}

async function runAI(mode, message = "") {
  if (aiBusy) return;
  setAIBusy(true);
  try {
    if (!$("#ai-dialog").open) {
      $("#ai-dialog").showModal();
      renderChat(await api(`${tripURL}/chat`));
    }
    $(".chat-welcome")?.remove();
    appendChat("user", message || (mode === "packing" ? "Build a tailored packing list for this holiday." : "Audit my trip readiness."));
    const result = await api(`${tripURL}/ai/${mode}`, {
      method: "POST", data: mode === "chat" ? { message } : {}, timeout: 110000,
    });
    if (mode === "chat") $("#chat-input").value = "";
    appendChat("assistant", result.message);
    await loadTrip();
    if (result.applied) toast(`${result.applied} ${result.applied === 1 ? "change" : "changes"} saved to your holiday.`);
  } catch (error) {
    appendChat("assistant", error.message, true);
    toast(error.message, true);
  } finally {
    setAIBusy(false);
    checkAI();
  }
}

$("#chat-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = $("#chat-input").value.trim();
  if (message) runAI("chat", message);
});

document.addEventListener("change", (event) => {
  const checkbox = event.target.closest("[data-packing-id]");
  if (!checkbox) return;
  const checked = checkbox.checked;
  checkbox.disabled = true;
  safely(async () => {
    try {
      await api(`${tripURL}/packing/${checkbox.dataset.packingId}`, { method: "PATCH", data: { packed: checked } });
      await loadTrip();
    } catch (error) {
      checkbox.checked = !checked;
      throw error;
    } finally {
      checkbox.disabled = false;
    }
  });
});

async function handleAction(button) {
  const action = button.dataset.action;
  const id = Number(button.dataset.id);
  if (action === "new-holiday") {
    const start = button.dataset.date || todayKey();
    openForm("holiday", { start_date: start, end_date: start });
  } else if (action === "refresh") {
    if (tripId) await loadTrip();
    else await loadDashboard();
  } else if (action === "templates") {
    await showTemplates();
  } else if (action === "delete-template") {
    const template = templates.find((entry) => entry.id === id);
    if (await confirmDelete("Delete packing template?", `Delete "${template.name}"? Existing holiday packing lists will not change.`)) {
      await api(`/api/templates/${id}`, { method: "DELETE" });
      await showTemplates();
      toast("Template deleted.");
    }
  } else if (action === "apply-template") {
    button.disabled = true;
    try {
      const result = await api(`${tripURL}/templates/${id}`, { method: "POST" });
      await loadTrip();
      $("#templates-dialog").close();
      toast(`${result.added} items added. Existing items were left as they were.`);
    } finally {
      button.disabled = false;
    }
  } else {
    if (!trip) throw new Error("Holiday details are not loaded yet. Refresh the page and try again.");
    if (action === "edit-holiday") openForm("holiday", trip, trip.id);
    else if (action === "delete-holiday") {
      if (await confirmDelete("Delete this holiday?", `Permanently delete "${trip.title}", including its packing list, flights, expenses, and conversation? Saved templates are kept.`)) {
        await api(tripURL, { method: "DELETE" });
        location.assign("/");
      }
    } else if (action === "print") {
      window.print();
    } else if (action === "open-ai") {
      await openAI();
    } else if (action === "generate-packing") {
      await runAI("packing");
    } else if (action === "audit") {
      await runAI("audit");
    } else {
      const [operation, kind] = action.split("-");
      const collections = { packing: "packing", flight: "flights", expense: "expenses" };
      const records = { packing: trip.packing_items, flight: trip.flights, expense: trip.expenses };
      if (!collections[kind]) return;
      if (operation === "add") openForm(kind, kind === "expense" ? { date: todayKey() } : {});
      if (operation === "edit") openForm(kind, records[kind].find((entry) => entry.id === id), id);
      if (operation === "delete") {
        const record = records[kind].find((entry) => entry.id === id);
        const label = record.name || record.flight_number || record.description;
        if (await confirmDelete(`Delete ${kind === "packing" ? "packing item" : kind}?`, `Remove "${label}" from this holiday?`)) {
          await api(`${tripURL}/${collections[kind]}/${id}`, { method: "DELETE" });
          await loadTrip();
          toast("Deleted from your holiday.");
        }
      }
    }
  }
}

document.addEventListener("click", (event) => {
  const close = event.target.closest("[data-close]");
  if (close) close.closest("dialog").close();
  const button = event.target.closest("[data-action]");
  if (button && !button.disabled) safely(() => handleAction(button));
  const filter = event.target.closest("[data-filter]");
  if (filter && trip) {
    packingFilter = filter.dataset.filter;
    $$("[data-filter]").forEach((element) => element.setAttribute("aria-pressed", String(element === filter)));
    renderPacking();
  }
});

if (tripId) {
  safely(loadTrip);
} else {
  $("#list-view-button").addEventListener("click", () => setDashboardView("list"));
  $("#calendar-view-button").addEventListener("click", () => setDashboardView("calendar"));
  $("#holiday-search").addEventListener("input", () => { if (dashboardLoaded) renderDashboard(); });
  $("#calendar-prev").addEventListener("click", () => {
    calendarMonth.setUTCMonth(calendarMonth.getUTCMonth() - 1);
    renderCalendar(filteredHolidays());
  });
  $("#calendar-next").addEventListener("click", () => {
    calendarMonth.setUTCMonth(calendarMonth.getUTCMonth() + 1);
    renderCalendar(filteredHolidays());
  });
  $("#calendar-today").addEventListener("click", () => {
    calendarMonth = parseDate(todayKey());
    calendarMonth.setUTCDate(1);
    renderCalendar(filteredHolidays());
  });
  loadDashboard();
}
checkAI();
setInterval(() => { if (!document.hidden && !aiBusy) checkAI(); }, 60000);
