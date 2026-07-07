import random
import threading

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
        self.lock = threading.Lock()

    def add_player(self, user_id):
        if user_id not in self.player_ids:
            self.player_ids.append(user_id)
            self.scores[user_id] = 0

    def to_dict(self, current_user_id):
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
    return None
