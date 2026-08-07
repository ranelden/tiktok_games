import random
import threading
import time

import auth
import videos

# Alphabet with no ambiguous characters (no 0/O, 1/I/L).
ROOM_CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
ROOM_CODE_LENGTH = 6

MIN_ROUNDS = 3
MAX_ROUNDS = 20
# Exponential-slider-style steps: fine-grained on short periods, coarser
# further out. None = entire history.
PERIOD_OPTIONS = [1, 3, 7, 14, 30, 60, 90, 180, 365, None]
TIMER_OPTIONS = {None, 15, 30, 60}

# Scoring: a single correct guess is worth 1 point (safe but limited). A
# multi-select vote is riskier: if fully correct, every player found pays out
# a big bonus; if a single pick is wrong, the whole vote fails and each wrong
# pick costs points.
SINGLE_CORRECT_POINTS = 1
MULTI_CORRECT_POINTS = 2
MULTI_WRONG_PENALTY = 1
# Bonus for the video's owner(s), automatic every round: points per player
# who didn't identify them among their picks.
BET_BONUS_PER_MISS = 2

_rooms = {}
_rooms_lock = threading.Lock()


class Room:
    def __init__(self, code, chef_id):
        self.code = code
        self.chef_id = chef_id
        self.status = "lobby"  # lobby | in_progress | finished
        self.num_rounds = 10
        self.period_days = None  # None = entire history
        self.timer_seconds = None
        self.player_ids = []  # join order
        self.scores = {}
        self.current_round = 0
        self.used_links = set()
        # Current round state
        self.round_video = None  # {"link":..., "liked_at":...}
        self.round_owners = set()  # user_ids who actually liked the video (can be several)
        self.round_voters = set()  # player_ids allowed/expected to vote this round (owners excluded)
        self.round_votes = {}  # voter_id -> set(guessed_user_ids)
        self.round_status = None  # None | voting | revealed
        self.round_started_at = None
        self.last_result = None  # {"owner_ids":[...], "votes":[...], "bonuses":[...]}
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
                        "username": auth.get_username(uid),
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
                    result = self.last_result
                round_data = {
                    "number": self.current_round,
                    "total": self.num_rounds,
                    "status": self.round_status,
                    "video": self.round_video,
                    "time_left": time_left,
                    "has_voted": current_user_id in self.round_votes,
                    "votes_in": len(self.round_votes),
                    "votes_expected": len(self.round_voters),
                    "is_owner": current_user_id in self.round_owners,
                    "result": result,
                }

            return {
                "code": self.code,
                "status": self.status,
                "chef_id": self.chef_id,
                "is_chef": current_user_id == self.chef_id,
                "config": {
                    "num_rounds": self.num_rounds,
                    "period_days": self.period_days,
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


def update_config(room, chef_id, num_rounds, period_days, timer_seconds):
    if room.chef_id != chef_id:
        return "Seul le chef peut modifier la configuration"
    if room.status != "lobby":
        return "La configuration est verrouillée, la partie a déjà commencé"
    if not isinstance(num_rounds, int) or not (MIN_ROUNDS <= num_rounds <= MAX_ROUNDS):
        return f"Le nombre de rounds doit être un entier entre {MIN_ROUNDS} et {MAX_ROUNDS}"
    if period_days not in PERIOD_OPTIONS:
        return "Période invalide"
    if timer_seconds not in TIMER_OPTIONS:
        return "Temps limite invalide"
    with room.lock:
        room.num_rounds = num_rounds
        room.period_days = period_days
        room.timer_seconds = timer_seconds
    return None


def _pool_by_owner(room):
    """Videos not drawn yet this game, grouped by each of their owners,
    excluding any video liked by literally every player in the room (nobody
    would be left to vote on it).

    Grouping by owner first (rather than a flat list of every video) is what
    makes the draw below fair: a player who liked 5000 videos and one who
    liked 50 both get an equal chance of being featured in a round, instead
    of the prolific liker dominating a flat random pick.
    """
    link_owners = {}
    link_info = {}
    for uid in room.player_ids:
        for item in videos.get_links(uid, room.period_days):
            link_owners.setdefault(item["link"], set()).add(uid)
            link_info[item["link"]] = item

    by_owner = {}
    total_players = len(room.player_ids)
    for link, owners in link_owners.items():
        if link in room.used_links or len(owners) >= total_players:
            continue
        entry = {"link": link, "liked_at": link_info[link]["liked_at"], "owners": owners}
        for owner_id in owners:
            by_owner.setdefault(owner_id, []).append(entry)
    return by_owner, len(link_owners)


def _no_video_message(room):
    _, total = _pool_by_owner(room)
    if total == 0:
        return "Aucun joueur n'a de vidéo likée sur cette période — essaie une période plus large."
    return "Toutes les vidéos disponibles sur cette période ont déjà été tirées cette partie."


def _draw_next_video(room):
    by_owner, _ = _pool_by_owner(room)
    if not by_owner:
        return False
    # Fair two-stage draw: pick a featured player uniformly among those who
    # still have an eligible video, then pick uniformly among their videos.
    owner_id = random.choice(list(by_owner.keys()))
    chosen = random.choice(by_owner[owner_id])
    room.round_video = {"link": chosen["link"], "liked_at": chosen["liked_at"]}
    room.round_owners = chosen["owners"]
    room.round_voters = set(room.player_ids) - room.round_owners
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
            message = _no_video_message(room)
            room.status = "lobby"
            room.current_round = 0
            return message
    return None


def _score_vote(guesses, owners):
    """1 pt for a correct single guess, 0 otherwise. For multi-select: a big
    bonus per player found if every pick is correct, otherwise a penalty per
    wrong pick (the whole vote fails as soon as one pick is incorrect)."""
    if len(guesses) == 1:
        return SINGLE_CORRECT_POINTS if guesses <= owners else 0
    wrong = guesses - owners
    if wrong:
        return -MULTI_WRONG_PENALTY * len(wrong)
    correct = guesses & owners
    return MULTI_CORRECT_POINTS * len(correct)


def _reveal(room):
    if room.round_status != "voting":
        return
    owners = room.round_owners

    votes_result = []
    for voter_id in room.round_voters:
        guesses = room.round_votes.get(voter_id, set())
        points = _score_vote(guesses, owners) if guesses else 0
        if points:
            room.scores[voter_id] = room.scores.get(voter_id, 0) + points
        votes_result.append(
            {
                "voter_id": voter_id,
                "guessed_user_ids": sorted(guesses),
                "points": points,
            }
        )

    # Automatic bonus for every owner: points per voter who didn't pick them.
    bonuses_result = []
    for owner_id in owners:
        found_by = sum(1 for uid in room.round_voters if owner_id in room.round_votes.get(uid, set()))
        missed_by = max(0, len(room.round_voters) - found_by)
        bonus = BET_BONUS_PER_MISS * missed_by
        if bonus:
            room.scores[owner_id] = room.scores.get(owner_id, 0) + bonus
        bonuses_result.append({"owner_id": owner_id, "missed_by": missed_by, "bonus": bonus})

    room.round_status = "revealed"
    room.last_result = {
        "owner_ids": sorted(owners),
        "votes": votes_result,
        "bonuses": bonuses_result,
    }


def _maybe_expire_timer(room):
    if room.status != "in_progress" or room.round_status != "voting" or not room.timer_seconds:
        return
    if time.time() - room.round_started_at >= room.timer_seconds:
        _reveal(room)


def submit_vote(room, voter_id, guessed_user_ids):
    if room.status != "in_progress":
        return "La partie n'est pas en cours"
    with room.lock:
        _maybe_expire_timer(room)
        if room.round_status != "voting":
            return "Le vote est clos pour ce round"
        if voter_id not in room.round_voters:
            return "Tu ne peux pas voter sur ta propre vidéo"
        guesses = set(guessed_user_ids)
        if not guesses:
            return "Choisis au moins un joueur"
        if voter_id in guesses:
            return "Tu ne peux pas voter pour toi-même"
        if not guesses.issubset(set(room.player_ids)):
            return "Joueur invalide"
        if voter_id in room.round_votes:
            return "Tu as déjà voté pour ce round"
        room.round_votes[voter_id] = guesses
        if len(room.round_votes) >= len(room.round_voters):
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


def restart_game(room, chef_id):
    """Replay in the same room (same code, same players, same config) without
    forcing everyone to leave and recreate/rejoin a fresh room."""
    if room.chef_id != chef_id:
        return "Seul le chef peut relancer la partie"
    if room.status not in ("finished", "lobby"):
        return "La partie est encore en cours"
    with room.lock:
        room.status = "lobby"
        room.current_round = 0
        room.used_links = set()
        room.scores = {uid: 0 for uid in room.player_ids}
        room.round_video = None
        room.round_owners = set()
        room.round_voters = set()
        room.round_votes = {}
        room.round_status = None
        room.round_started_at = None
        room.last_result = None
    return None
