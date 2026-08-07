const views = document.querySelectorAll(".view");

// Must stay in sync with game.PERIOD_OPTIONS server-side (same order, same values).
const PERIOD_OPTIONS = [
  { days: 1, label: "1 jour" },
  { days: 3, label: "3 jours" },
  { days: 7, label: "1 semaine" },
  { days: 14, label: "2 semaines" },
  { days: 30, label: "1 mois" },
  { days: 60, label: "2 mois" },
  { days: 90, label: "3 mois" },
  { days: 180, label: "6 mois" },
  { days: 365, label: "1 an" },
  { days: null, label: "Tout l'historique" },
];

let currentUserId = null;
let currentRoomCode = null;
let roomPollInterval = null;
const previousScores = {};

function showView(id) {
  if (id !== "view-room") stopRoomPolling();
  views.forEach((v) => {
    v.hidden = v.id !== id;
  });
  const target = document.getElementById(id);
  target.classList.remove("view-enter");
  void target.offsetWidth; // force a reflow so the animation replays every time
  target.classList.add("view-enter");
}

function animateNumber(el, from, to, duration) {
  if (from === to) {
    el.textContent = to;
    return;
  }
  const start = performance.now();
  function tick(now) {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = Math.round(from + (to - from) * eased);
    if (t < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

function renderDashboard(data) {
  currentUserId = data.user_id;
  document.getElementById("dashboard-email").textContent = data.email;
  document.getElementById("dashboard-count").textContent = data.video_count;
  document.getElementById("username-input").value = data.username;
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
  for (const key in previousScores) delete previousScores[key];
  lastEmbeddedLink = null;
  lastChoicesRound = null;
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
    li.className = "player-row";

    const nameSpan = document.createElement("span");
    nameSpan.className = "player-name";
    nameSpan.textContent = p.username + (p.has_data ? "" : " (données manquantes)");

    const scoreSpan = document.createElement("span");
    scoreSpan.className = "player-score";
    const valueSpan = document.createElement("span");
    valueSpan.className = "score-value";
    const deltaSpan = document.createElement("span");
    deltaSpan.className = "score-delta";

    const previous = previousScores[p.user_id];
    const from = previous === undefined ? p.score : previous;
    valueSpan.textContent = from;
    animateNumber(valueSpan, from, p.score, 600);

    if (previous !== undefined && previous !== p.score) {
      const delta = p.score - previous;
      deltaSpan.textContent = `${delta > 0 ? "+" : ""}${delta}`;
      deltaSpan.classList.add(delta > 0 ? "positive" : "negative", "show");
      scoreSpan.classList.add("score-flash");
      setTimeout(() => scoreSpan.classList.remove("score-flash"), 1000);
    }
    previousScores[p.user_id] = p.score;

    scoreSpan.appendChild(valueSpan);
    scoreSpan.appendChild(document.createTextNode(" pts"));
    scoreSpan.appendChild(deltaSpan);

    li.appendChild(nameSpan);
    li.appendChild(scoreSpan);
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
    document.getElementById("config-timer").value =
      room.config.timer_seconds === null ? "" : room.config.timer_seconds;
    const periodIdx = PERIOD_OPTIONS.findIndex((o) => o.days === room.config.period_days);
    setPeriodSlider(periodIdx === -1 ? PERIOD_OPTIONS.length - 1 : periodIdx);
  }

  if (room.status === "in_progress" && room.round) {
    renderRound(room);
  }

  if (room.status === "finished") {
    renderFinal(room);
  }
}

let lastEmbeddedLink = null;
let lastChoicesRound = null;

function renderTikTokEmbed(link) {
  const container = document.getElementById("round-video-embed");
  const match = link.match(/video\/(\d+)/);
  if (!match) {
    container.innerHTML = "";
    return;
  }
  const videoId = match[1];
  container.innerHTML =
    `<blockquote class="tiktok-embed" cite="${link}" data-video-id="${videoId}" ` +
    `style="max-width:325px;min-width:280px;margin:0 auto;"><section></section></blockquote>`;
  // TikTok doesn't auto-rescan the DOM for a blockquote added after the fact
  // (SPA): force it to process the new one by reinjecting the script.
  const old = document.getElementById("tiktok-embed-script");
  if (old) old.remove();
  const script = document.createElement("script");
  script.id = "tiktok-embed-script";
  script.async = true;
  script.src = "https://www.tiktok.com/embed.js";
  document.body.appendChild(script);
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

  if (r.video.link !== lastEmbeddedLink) {
    lastEmbeddedLink = r.video.link;
    renderTikTokEmbed(r.video.link);
  }

  const votingEl = document.getElementById("round-voting");
  const revealedEl = document.getElementById("round-revealed");
  const ownerViewEl = document.getElementById("round-owner-view");
  votingEl.hidden = r.status !== "voting" || r.is_owner;
  revealedEl.hidden = r.status !== "revealed";
  ownerViewEl.hidden = !(r.status === "voting" && r.is_owner);

  if (r.status === "voting" && !r.is_owner) {
    const voteForm = document.getElementById("round-vote-form");
    const waitingEl = document.getElementById("round-waiting-votes");
    if (r.has_voted) {
      voteForm.hidden = true;
      waitingEl.hidden = false;
      waitingEl.textContent = `En attente des autres joueurs... (${r.votes_in}/${r.votes_expected})`;
    } else {
      voteForm.hidden = false;
      waitingEl.hidden = true;
      // Only (re)build the checkboxes once per round: this view re-renders on
      // every poll tick (every 2s), and rebuilding the DOM each time was
      // wiping out choices the player had already checked but not submitted.
      if (lastChoicesRound !== r.number) {
        lastChoicesRound = r.number;
        const choicesEl = document.getElementById("round-choices");
        choicesEl.innerHTML = "";
        room.players
          .filter((p) => p.user_id !== currentUserId)
          .forEach((p) => {
            const label = document.createElement("label");
            label.className = "choice-checkbox";
            const input = document.createElement("input");
            input.type = "checkbox";
            input.value = p.user_id;
            label.appendChild(input);
            label.appendChild(document.createTextNode(p.username));
            choicesEl.appendChild(label);
          });
      }
    }
  }

  if (r.status === "revealed" && r.result) {
    const ownerNames =
      r.result.owner_ids
        .map((id) => room.players.find((p) => p.user_id === id))
        .filter(Boolean)
        .map((p) => p.username)
        .join(", ") || "?";
    document.getElementById("round-answer").textContent = `C'était : ${ownerNames}`;

    const list = document.getElementById("round-votes-list");
    list.innerHTML = "";
    r.result.votes.forEach((v) => {
      const voter = room.players.find((p) => p.user_id === v.voter_id);
      const guessedNames =
        v.guessed_user_ids
          .map((id) => room.players.find((p) => p.user_id === id))
          .filter(Boolean)
          .map((p) => p.username)
          .join(", ") || "personne (temps écoulé)";
      const li = document.createElement("li");
      const sign = v.points > 0 ? "+" : "";
      li.textContent = `${voter ? voter.username : "?"} a voté ${guessedNames} — ${sign}${v.points} pt(s)`;
      if (v.points > 0) li.classList.add("result-positive");
      else if (v.points < 0) li.classList.add("result-negative");
      list.appendChild(li);
    });

    const bonusList = document.getElementById("round-bets-list");
    bonusList.innerHTML = "";
    r.result.bonuses.forEach((b) => {
      const owner = room.players.find((p) => p.user_id === b.owner_id);
      const li = document.createElement("li");
      li.textContent = `${owner ? owner.username : "?"} : ${b.missed_by} joueur(s) ne l'ont pas trouvé — +${b.bonus} pt(s) bonus`;
      bonusList.appendChild(li);
    });

    document.getElementById("round-next-button").hidden = !room.is_chef;
    document.getElementById("round-next-waiting").hidden = room.is_chef;
  }
}

function renderFinal(room) {
  const sorted = [...room.players].sort((a, b) => b.score - a.score);
  const top3 = sorted.slice(0, 3);
  const rest = sorted.slice(3);

  const podium = document.getElementById("podium");
  podium.innerHTML = "";
  // Classic podium layout: 2nd place on the left, 1st in the middle, 3rd on the right.
  const order = [top3[1], top3[0], top3[2]];
  order.forEach((p) => {
    if (!p) return;
    const rank = top3.indexOf(p) + 1;
    const place = document.createElement("div");
    place.className = `podium-place rank-${rank}`;

    const name = document.createElement("div");
    name.className = "podium-name";
    name.textContent = p.username;

    const score = document.createElement("div");
    score.className = "podium-score";
    score.textContent = `${p.score} pts`;

    const bar = document.createElement("div");
    bar.className = "podium-bar";
    bar.textContent = `#${rank}`;

    place.appendChild(name);
    place.appendChild(score);
    place.appendChild(bar);
    podium.appendChild(place);
  });

  const list = document.getElementById("final-scoreboard-rest");
  list.innerHTML = "";
  rest.forEach((p, i) => {
    const li = document.createElement("li");
    li.textContent = `#${i + 4} — ${p.username} — ${p.score} pts`;
    list.appendChild(li);
  });

  document.getElementById("room-restart-button").hidden = !room.is_chef;
  document.getElementById("room-restart-waiting").hidden = room.is_chef;
}

function setPeriodSlider(idx) {
  const slider = document.getElementById("config-period-slider");
  slider.value = idx;
  document.getElementById("config-period-label").textContent = PERIOD_OPTIONS[idx].label;
}

async function castVote(guessedUserIds) {
  const messageEl = document.getElementById("round-message");
  const { ok, data } = await voteRequest(currentRoomCode, guessedUserIds);
  if (!ok) {
    messageEl.textContent = data.error || "Erreur";
    return;
  }
  messageEl.textContent = "";
  renderRoom(data);
}

document.getElementById("round-vote-submit").addEventListener("click", async () => {
  const checked = Array.from(document.querySelectorAll("#round-choices input:checked")).map((el) =>
    parseInt(el.value, 10)
  );
  if (checked.length === 0) {
    document.getElementById("round-message").textContent = "Sélectionne au moins un joueur.";
    return;
  }
  await castVote(checked);
});

document.getElementById("room-restart-button").addEventListener("click", async () => {
  const messageEl = document.getElementById("room-restart-message");
  const { ok, data } = await restartRoomRequest(currentRoomCode);
  if (!ok) {
    messageEl.textContent = data.error || "Erreur";
    return;
  }
  messageEl.textContent = "";
  renderRoom(data);
});

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

document.getElementById("config-period-slider").addEventListener("input", (e) => {
  document.getElementById("config-period-label").textContent = PERIOD_OPTIONS[parseInt(e.target.value, 10)].label;
});

document.getElementById("room-config-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const num_rounds = parseInt(document.getElementById("config-num-rounds").value, 10);
  const periodIdx = parseInt(document.getElementById("config-period-slider").value, 10);
  const period_days = PERIOD_OPTIONS[periodIdx].days;
  const timerRaw = document.getElementById("config-timer").value;
  const timer_seconds = timerRaw === "" ? null : parseInt(timerRaw, 10);
  const messageEl = document.getElementById("room-config-message");
  const { ok, data } = await updateRoomConfig(currentRoomCode, { num_rounds, period_days, timer_seconds });
  if (!ok) {
    messageEl.textContent = data.error || "Erreur";
    return;
  }
  messageEl.textContent = "Config mise à jour.";
  renderRoom(data);
});

document.getElementById("username-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("username-input").value.trim();
  const messageEl = document.getElementById("username-message");
  const { ok, data } = await updateUsername(name);
  if (!ok) {
    messageEl.textContent = data.error || "Erreur";
    return;
  }
  messageEl.textContent = "Pseudo mis à jour.";
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
