import random
import threading
import time

import auth
import videos

# Alphabet sans caractères ambigus (pas de 0/O, 1/I/L).
ROOM_CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
ROOM_CODE_LENGTH = 6

MIN_ROUNDS = 3
MAX_ROUNDS = 20
PERIOD_FILTERS = {"7d", "30d", "all"}
TIMER_OPTIONS = {None, 15, 30, 60}

_rooms = {}
_rooms_lock = threading.Lock()


class Room:
    def __init__(self, code, chef_id):
        self.code = code
        self.chef_id = chef_id
        self.status = "lobby"  # lobby | in_progress | finished
        self.num_rounds = 10
        self.period_filter = "all"
        self.timer_seconds = None
        self.player_ids = []  # ordre d'arrivée
        self.scores = {}
        self.current_round = 0
        self.used_links = set()
        # État du round courant
        self.round_video = None  # {"link":..., "liked_at":...}
        self.round_owner = None  # user_id qui a réellement liké la vidéo
        self.round_votes = {}  # voter_id -> guessed_user_id
        self.round_status = None  # None | voting | revealed
        self.round_started_at = None
        self.last_result = None  # {"owner_id":..., "votes":[...]}
        self.lock = threading.RLock()

    def add_player(self, user_id):
        if user_id not in self.player_ids:
            self.player_ids.append(user_id)
            self.scores[user_id] = 0

    def to_dict(self, current_user_id):
        with self.lock:
            _maybe_expire_timer(self)

            players = []
            for uid in self.player_ids:
                user = auth.get_user_by_id(uid)
                players.append(
                    {
                        "user_id": uid,
                        "email": user["email"] if user else "?",
                        "score": self.scores.get(uid, 0),
                        "has_data": videos.has_videos(uid),
                    }
                )

            round_data = None
            if self.round_video is not None:
                time_left = None
                if self.round_status == "voting" and self.timer_seconds:
                    elapsed = time.time() - self.round_started_at
                    time_left = max(0, int(self.timer_seconds - elapsed))
                result = None
                if self.round_status == "revealed" and self.last_result:
                    result = {
                        "owner_id": self.last_result["owner_id"],
                        "votes": self.last_result["votes"],
                    }
                round_data = {
                    "number": self.current_round,
                    "total": self.num_rounds,
                    "status": self.round_status,
                    "video": self.round_video,
                    "time_left": time_left,
                    "has_voted": current_user_id in self.round_votes,
                    "votes_in": len(self.round_votes),
                    "votes_expected": len(self.player_ids),
                    "result": result,
                }

            return {
                "code": self.code,
                "status": self.status,
                "chef_id": self.chef_id,
                "is_chef": current_user_id == self.chef_id,
                "config": {
                    "num_rounds": self.num_rounds,
                    "period_filter": self.period_filter,
                    "timer_seconds": self.timer_seconds,
                },
                "players": players,
                "round": round_data,
            }


def _generate_code():
    while True:
        code = "".join(random.choices(ROOM_CODE_CHARS, k=ROOM_CODE_LENGTH))
        if code not in _rooms:
            return code


def create_room(chef_id):
    with _rooms_lock:
        code = _generate_code()
        room = Room(code, chef_id)
        room.add_player(chef_id)
        _rooms[code] = room
        return room


def get_room(code):
    if not code:
        return None
    return _rooms.get(code.upper())


def join_room(code, user_id):
    room = get_room(code)
    if room is None:
        return None, "Room introuvable"
    if room.status != "lobby":
        return None, "La partie a déjà commencé"
    with room.lock:
        room.add_player(user_id)
    return room, None


def update_config(room, chef_id, num_rounds, period_filter, timer_seconds):
    if room.chef_id != chef_id:
        return "Seul le chef peut modifier la configuration"
    if room.status != "lobby":
        return "La configuration est verrouillée, la partie a déjà commencé"
    if not isinstance(num_rounds, int) or not (MIN_ROUNDS <= num_rounds <= MAX_ROUNDS):
        return f"Le nombre de rounds doit être un entier entre {MIN_ROUNDS} et {MAX_ROUNDS}"
    if period_filter not in PERIOD_FILTERS:
        return "Filtre de période invalide"
    if timer_seconds not in TIMER_OPTIONS:
        return "Temps limite invalide"
    with room.lock:
        room.num_rounds = num_rounds
        room.period_filter = period_filter
        room.timer_seconds = timer_seconds
    return None


def _build_pool(room):
    """Vidéos likées par un seul joueur de la room (pas déjà tirées), pour éviter
    les réponses ambiguës quand plusieurs joueurs ont liké la même vidéo."""
    link_owners = {}
    link_info = {}
    for uid in room.player_ids:
        for item in videos.get_links(uid, room.period_filter):
            link_owners.setdefault(item["link"], set()).add(uid)
            link_info[item["link"]] = item
    pool = []
    for link, owners in link_owners.items():
        if len(owners) == 1 and link not in room.used_links:
            pool.append({"link": link, "liked_at": link_info[link]["liked_at"], "owner": next(iter(owners))})
    return pool


def _draw_next_video(room):
    pool = _build_pool(room)
    if not pool:
        return False
    chosen = random.choice(pool)
    room.round_video = {"link": chosen["link"], "liked_at": chosen["liked_at"]}
    room.round_owner = chosen["owner"]
    room.round_votes = {}
    room.round_status = "voting"
    room.round_started_at = time.time()
    room.last_result = None
    room.used_links.add(chosen["link"])
    return True


def start_game(room, chef_id):
    if room.chef_id != chef_id:
        return "Seul le chef peut lancer la partie"
    if room.status != "lobby":
        return "La partie a déjà commencé"
    if len(room.player_ids) < 2:
        return "Il faut au moins 2 joueurs pour lancer la partie"
    not_ready = [uid for uid in room.player_ids if not videos.has_videos(uid)]
    if not_ready:
        return "Tous les joueurs doivent avoir importé leurs données avant de lancer la partie"
    with room.lock:
        room.status = "in_progress"
        room.current_round = 1
        if not _draw_next_video(room):
            room.status = "lobby"
            room.current_round = 0
            return "Aucune vidéo exploitable pour lancer la partie (essaie une période plus large)"
    return None


def _reveal(room):
    if room.round_status != "voting":
        return
    results = []
    for voter_id in room.player_ids:
        guess = room.round_votes.get(voter_id)
        correct = guess is not None and guess == room.round_owner
        if correct:
            room.scores[voter_id] = room.scores.get(voter_id, 0) + 1
        results.append({"voter_id": voter_id, "guessed_user_id": guess, "correct": correct})
    room.round_status = "revealed"
    room.last_result = {"owner_id": room.round_owner, "votes": results}


def _maybe_expire_timer(room):
    if room.status != "in_progress" or room.round_status != "voting" or not room.timer_seconds:
        return
    if time.time() - room.round_started_at >= room.timer_seconds:
        _reveal(room)


def submit_vote(room, voter_id, guessed_user_id):
    if room.status != "in_progress":
        return "La partie n'est pas en cours"
    with room.lock:
        _maybe_expire_timer(room)
        if room.round_status != "voting":
            return "Le vote est clos pour ce round"
        if voter_id not in room.player_ids:
            return "Tu ne fais pas partie de cette room"
        if guessed_user_id not in room.player_ids:
            return "Joueur invalide"
        if guessed_user_id == voter_id:
            return "Tu ne peux pas voter pour toi-même"
        if voter_id in room.round_votes:
            return "Tu as déjà voté pour ce round"
        room.round_votes[voter_id] = guessed_user_id
        if len(room.round_votes) >= len(room.player_ids):
            _reveal(room)
    return None


def advance_round(room, chef_id):
    if room.chef_id != chef_id:
        return "Seul le chef peut passer au round suivant"
    with room.lock:
        _maybe_expire_timer(room)
        if room.status != "in_progress":
            return "La partie n'est pas en cours"
        if room.round_status != "revealed":
            return "Le round en cours n'est pas encore révélé"
        if room.current_round >= room.num_rounds:
            room.status = "finished"
            room.round_status = None
            return None
        room.current_round += 1
        if not _draw_next_video(room):
            room.status = "finished"
            room.round_status = None
    return None
