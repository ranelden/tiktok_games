function createRoomRequest() {
  return apiPostJson("/api/rooms", {});
}

function joinRoomRequest(code) {
  return apiPostJson(`/api/rooms/${code}/join`, {});
}

function getRoomState(code) {
  return apiGet(`/api/rooms/${code}`);
}

function updateRoomConfig(code, config) {
  return apiPostJson(`/api/rooms/${code}/config`, config);
}

function startRoomGame(code) {
  return apiPostJson(`/api/rooms/${code}/start`, {});
}

function voteRequest(code, guessedUserIds) {
  return apiPostJson(`/api/rooms/${code}/vote`, { guessed_user_ids: guessedUserIds });
}

function nextRoundRequest(code) {
  return apiPostJson(`/api/rooms/${code}/next`, {});
}

function restartRoomRequest(code) {
  return apiPostJson(`/api/rooms/${code}/restart`, {});
}
