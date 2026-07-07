const views = document.querySelectorAll(".view");

let currentUserId = null;
let currentRoomCode = null;
let roomPollInterval = null;

function showView(id) {
  if (id !== "view-room") stopRoomPolling();
  views.forEach((v) => {
    v.hidden = v.id !== id;
  });
}

function renderDashboard(data) {
  currentUserId = data.user_id;
  document.getElementById("dashboard-email").textContent = data.email;
  document.getElementById("dashboard-count").textContent = data.video_count;
  showView("view-dashboard");
}

function stopRoomPolling() {
  if (roomPollInterval) {
    clearInterval(roomPollInterval);
    roomPollInterval = null;
  }
}

function enterRoom(code) {
  currentRoomCode = code;
  showView("view-room");
  refreshRoom();
  roomPollInterval = setInterval(refreshRoom, 2000);
}

async function refreshRoom() {
  if (!currentRoomCode) return;
  const { ok, data } = await getRoomState(currentRoomCode);
  if (!ok) {
    stopRoomPolling();
    showView("view-dashboard");
    return;
  }
  renderRoom(data);
}

function renderRoom(room) {
  document.getElementById("room-code-display").textContent = room.code;

  const list = document.getElementById("room-players-list");
  list.innerHTML = "";
  room.players.forEach((p) => {
    const li = document.createElement("li");
    li.textContent = `${p.email} — score : ${p.score}${p.has_data ? "" : " (données manquantes)"}`;
    list.appendChild(li);
  });

  const me = room.players.find((p) => p.user_id === currentUserId);
  document.getElementById("room-not-ready-warning").hidden = !(me && !me.has_data);

  document.getElementById("room-chef-config").hidden = !(room.is_chef && room.status === "lobby");
  document.getElementById("room-waiting").hidden = !(!room.is_chef && room.status === "lobby");
  document.getElementById("room-in-progress").hidden = room.status === "lobby";

  if (room.status === "lobby") {
    document.getElementById("config-num-rounds").value = room.config.num_rounds;
    document.getElementById("config-period-filter").value = room.config.period_filter;
    document.getElementById("config-timer").value =
      room.config.timer_seconds === null ? "" : room.config.timer_seconds;
  }
}

document.getElementById("show-login").addEventListener("click", () => showView("view-login"));
document.getElementById("show-register").addEventListener("click", () => showView("view-register"));
document.querySelectorAll("[data-back]").forEach((btn) => {
  btn.addEventListener("click", () => showView("view-landing"));
});

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("login-email").value;
  const password = document.getElementById("login-password").value;
  const messageEl = document.getElementById("login-message");
  messageEl.textContent = "Connexion...";
  const { ok, data } = await login(email, password);
  if (!ok) {
    messageEl.textContent = data.error || "Erreur de connexion";
    return;
  }
  messageEl.textContent = "";
  renderDashboard(data);
});

let registerFile = null;
setupDropzone(
  document.getElementById("register-dropzone"),
  document.getElementById("register-file"),
  (file) => {
    registerFile = file;
    document.getElementById("register-filename").textContent = file.name;
  }
);

document.getElementById("register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("register-email").value;
  const password = document.getElementById("register-password").value;
  const messageEl = document.getElementById("register-message");
  messageEl.textContent = "Création du compte...";
  const { ok, data } = await register(email, password, registerFile);
  if (!ok) {
    messageEl.textContent = data.error || "Erreur lors de la création du compte";
    return;
  }
  messageEl.textContent = "";
  renderDashboard(data);
});

setupDropzone(
  document.getElementById("update-dropzone"),
  document.getElementById("update-file"),
  async (file) => {
    const messageEl = document.getElementById("update-message");
    messageEl.textContent = "Import en cours...";
    const { ok, data } = await updateData(file);
    if (!ok) {
      messageEl.textContent = data.error || "Erreur lors de l'import";
      return;
    }
    document.getElementById("dashboard-count").textContent = data.video_count;
    messageEl.textContent = "Données mises à jour.";
  }
);

document.getElementById("create-room-button").addEventListener("click", async () => {
  const messageEl = document.getElementById("room-message");
  const { ok, data } = await createRoomRequest();
  if (!ok) {
    messageEl.textContent = data.error || "Erreur";
    return;
  }
  messageEl.textContent = "";
  enterRoom(data.code);
});

document.getElementById("join-room-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = document.getElementById("join-room-code").value.trim().toUpperCase();
  const messageEl = document.getElementById("room-message");
  const { ok, data } = await joinRoomRequest(code);
  if (!ok) {
    messageEl.textContent = data.error || "Erreur";
    return;
  }
  messageEl.textContent = "";
  enterRoom(code);
});

document.getElementById("room-config-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const num_rounds = parseInt(document.getElementById("config-num-rounds").value, 10);
  const period_filter = document.getElementById("config-period-filter").value;
  const timerRaw = document.getElementById("config-timer").value;
  const timer_seconds = timerRaw === "" ? null : parseInt(timerRaw, 10);
  const messageEl = document.getElementById("room-config-message");
  const { ok, data } = await updateRoomConfig(currentRoomCode, { num_rounds, period_filter, timer_seconds });
  if (!ok) {
    messageEl.textContent = data.error || "Erreur";
    return;
  }
  messageEl.textContent = "Config mise à jour.";
  renderRoom(data);
});

document.getElementById("room-start-button").addEventListener("click", async () => {
  const messageEl = document.getElementById("room-config-message");
  const { ok, data } = await startRoomGame(currentRoomCode);
  if (!ok) {
    messageEl.textContent = data.error || "Erreur";
    return;
  }
  renderRoom(data);
});

document.getElementById("room-go-upload").addEventListener("click", () => {
  showView("view-dashboard");
});

document.getElementById("room-leave-button").addEventListener("click", () => {
  showView("view-dashboard");
});

document.getElementById("logout-button").addEventListener("click", async () => {
  await logout();
  currentUserId = null;
  currentRoomCode = null;
  showView("view-landing");
});

fetch("/api/health")
  .then((res) => res.json())
  .then((data) => {
    document.getElementById("health").textContent = data.status;
  })
  .catch(() => {
    document.getElementById("health").textContent = "erreur";
  });

(async () => {
  const { ok, data } = await fetchMe();
  if (ok) {
    renderDashboard(data);
  } else {
    showView("view-landing");
  }
})();
