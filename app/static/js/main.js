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
  document.getElementById("room-in-progress").hidden = room.status !== "in_progress";
  document.getElementById("room-finished").hidden = room.status !== "finished";

  if (room.status === "lobby") {
    document.getElementById("config-num-rounds").value = room.config.num_rounds;
    document.getElementById("config-period-filter").value = room.config.period_filter;
    document.getElementById("config-timer").value =
      room.config.timer_seconds === null ? "" : room.config.timer_seconds;
  }

  if (room.status === "in_progress" && room.round) {
    renderRound(room);
  }

  if (room.status === "finished") {
    renderFinal(room);
  }
}

function renderRound(room) {
  const r = room.round;
  document.getElementById("round-number").textContent = r.number;
  document.getElementById("round-total").textContent = r.total;
  document.getElementById("round-timer").textContent =
    r.time_left !== null ? `Temps restant : ${r.time_left}s` : "";
  document.getElementById("round-video-link").href = r.video.link;
  document.getElementById("round-video-date").textContent = r.video.liked_at
    ? `Likée le ${r.video.liked_at}`
    : "";

  const votingEl = document.getElementById("round-voting");
  const revealedEl = document.getElementById("round-revealed");
  votingEl.hidden = r.status !== "voting";
  revealedEl.hidden = r.status !== "revealed";

  if (r.status === "voting") {
    const choicesEl = document.getElementById("round-choices");
    const waitingEl = document.getElementById("round-waiting-votes");
    if (r.has_voted) {
      choicesEl.hidden = true;
      waitingEl.textContent = `En attente des autres joueurs... (${r.votes_in}/${r.votes_expected})`;
    } else {
      choicesEl.hidden = false;
      waitingEl.textContent = "";
      choicesEl.innerHTML = "";
      room.players
        .filter((p) => p.user_id !== currentUserId)
        .forEach((p) => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.textContent = p.email;
          btn.addEventListener("click", () => castVote(p.user_id));
          choicesEl.appendChild(btn);
        });
    }
  }

  if (r.status === "revealed" && r.result) {
    const ownerPlayer = room.players.find((p) => p.user_id === r.result.owner_id);
    document.getElementById("round-answer").textContent = `C'était ${
      ownerPlayer ? ownerPlayer.email : "?"
    } !`;

    const list = document.getElementById("round-votes-list");
    list.innerHTML = "";
    r.result.votes.forEach((v) => {
      const voter = room.players.find((p) => p.user_id === v.voter_id);
      const guessed = room.players.find((p) => p.user_id === v.guessed_user_id);
      const li = document.createElement("li");
      li.textContent = `${voter ? voter.email : "?"} a voté ${
        guessed ? guessed.email : "personne (temps écoulé)"
      } — ${v.correct ? "✓" : "✗"}`;
      list.appendChild(li);
    });

    document.getElementById("round-next-button").hidden = !room.is_chef;
    document.getElementById("round-next-waiting").hidden = room.is_chef;
  }
}

function renderFinal(room) {
  const sorted = [...room.players].sort((a, b) => b.score - a.score);
  const list = document.getElementById("final-scoreboard");
  list.innerHTML = "";
  sorted.forEach((p, i) => {
    const li = document.createElement("li");
    li.textContent = `#${i + 1} — ${p.email} — ${p.score} pts`;
    list.appendChild(li);
  });
}

async function castVote(guessedUserId) {
  const messageEl = document.getElementById("round-message");
  const { ok, data } = await voteRequest(currentRoomCode, guessedUserId);
  if (!ok) {
    messageEl.textContent = data.error || "Erreur";
    return;
  }
  messageEl.textContent = "";
  renderRoom(data);
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

document.getElementById("round-next-button").addEventListener("click", async () => {
  const messageEl = document.getElementById("round-message");
  const { ok, data } = await nextRoundRequest(currentRoomCode);
  if (!ok) {
    messageEl.textContent = data.error || "Erreur";
    return;
  }
  messageEl.textContent = "";
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
