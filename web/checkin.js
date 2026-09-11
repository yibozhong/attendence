const el = (id) => document.getElementById(id);
let token = location.hash.slice(1);
try {
  token = token || sessionStorage.getItem("attendance_admin") || "";
  if (token) sessionStorage.setItem("attendance_admin", token);
} catch (_) { /* Check-in also works with browser storage disabled. */ }
if (location.hash) history.replaceState(null, "", location.pathname);

let session = null;
let selected = null;
let busy = false;
let connected = false;
let refreshing = false;
let revision = 0;
let rosterVersion = "";

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST", cache: "no-store",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The request failed. Please try again.");
  return data;
}

function updateControls() {
  el("submit").disabled = busy || !connected || !session?.open || selected === null;
  el("toggle").disabled = busy || !connected;
  el("search").disabled = busy;
  el("choices").disabled = busy;
}

function resetSelection() {
  selected = null;
  el("selection").textContent = "Select your own name before confirming.";
}

function renderRoster() {
  const query = el("search").value.trim().toLocaleLowerCase("en-US");
  const matches = (session?.students || []).filter((s) => s.name.toLocaleLowerCase("en-US").includes(query));
  const list = document.createDocumentFragment();
  for (const student of matches) {
    const label = document.createElement("label");
    label.className = "name-option";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "student";
    radio.value = student.id;
    radio.checked = student.id === selected;
    radio.addEventListener("change", () => {
      selected = student.id;
      el("selection").textContent = `Confirming attendance for: ${student.name}`;
      el("success").hidden = true;
      el("error").textContent = "";
      updateControls();
    });
    label.append(radio, document.createTextNode(student.name));
    list.append(label);
  }
  if (!matches.length) {
    const empty = document.createElement("p");
    empty.className = "hint empty-roster";
    empty.textContent = "No matching names. Try another spelling or ask your instructor.";
    list.append(empty);
  }
  el("roster").replaceChildren(list);
}

function render(data) {
  const wasOpen = session?.open;
  session = data;
  el("lab").textContent = data.lab;
  el("badge").textContent = data.open ? "Check-in open" : "Check-in closed";
  el("badge").classList.toggle("open", data.open);
  el("status").textContent = data.open
    ? "Select your own name below, then click Check in."
    : data.can_manage ? "Click Open check-in when the class is ready."
    : "Check-in is closed. Please ask your instructor to open it.";
  el("form").hidden = !data.open;
  el("toggle").hidden = !data.can_manage;
  el("toggle").textContent = data.open ? "Close check-in" : "Open check-in";
  el("toggle").classList.toggle("close", data.open);
  el("unique-count").textContent = data.unique_count;
  el("count").textContent = data.count;
  el("total").textContent = data.total;
  const rows = data.submissions.map((submission) => {
    const row = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = submission.name;
    const time = document.createElement("time");
    time.dateTime = submission.time.replace(" ", "T");
    time.textContent = new Date(time.dateTime).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    row.append(name, time);
    return row;
  });
  if (!rows.length) {
    const empty = document.createElement("li");
    empty.textContent = "No check-ins yet.";
    rows.push(empty);
  }
  el("submissions").replaceChildren(...rows);
  const version = JSON.stringify(data.students);
  if (version !== rosterVersion) {
    rosterVersion = version;
    if (!data.students.some((s) => s.id === selected)) resetSelection();
    renderRoster();
  }
  updateControls();
  if (data.open && !wasOpen) el("search").focus();
}

async function refresh() {
  if (busy || refreshing) return;
  refreshing = true;
  const requestRevision = revision;
  try {
    const data = await api("/api/session");
    if (busy || requestRevision !== revision) return;
    connected = true;
    render(data);
    el("connection-error").textContent = "";
  } catch (_) {
    if (busy || requestRevision !== revision) return;
    connected = false;
    el("connection-error").textContent = "Cannot reach the check-in server. Make sure it is running; this page will retry automatically.";
    updateControls();
  } finally { refreshing = false; }
}

el("search").addEventListener("input", () => {
  resetSelection();
  el("success").hidden = true;
  el("error").textContent = "";
  renderRoster();
  updateControls();
});

el("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || !connected || !session?.open || selected === null) return;
  busy = true;
  revision++;
  updateControls();
  el("submit").textContent = "Saving…";
  el("error").textContent = "";
  el("success").hidden = true;
  try {
    const data = await api("/api/checkin", { student_id: selected });
    resetSelection();
    el("search").value = "";
    render(data.session);
    renderRoster();
    el("roster").scrollTop = 0;
    el("success").textContent = `${data.name} is checked in. 10 points saved. Ready for the next student.`;
    el("success").hidden = false;
  } catch (error) {
    el("error").textContent = error.message || "Could not save. Please try again.";
  } finally {
    busy = false;
    el("submit").textContent = "Check in · 10 points";
    updateControls();
    el("search").focus();
  }
});

el("toggle").addEventListener("click", async () => {
  if (busy || !connected || !session?.can_manage) return;
  busy = true;
  revision++;
  updateControls();
  try {
    const data = await api(session.open ? "/api/admin/close" : "/api/admin/open", {});
    resetSelection();
    el("search").value = "";
    el("success").hidden = true;
    el("error").textContent = "";
    render(data);
  } catch (error) { el("error").textContent = error.message; }
  finally {
    busy = false;
    updateControls();
    if (session?.open) el("search").focus();
  }
});

refresh();
setInterval(refresh, 3000);
