import math
import random
import threading
import time
from datetime import datetime, timedelta

import auth
import availability
import videos

# Alphabet with no ambiguous characters (no 0/O, 1/I/L).
ROOM_CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
ROOM_CODE_LENGTH = 6

MIN_ROUNDS = 3
MAX_ROUNDS = 60
# Exponential-slider-style steps: fine-grained on short periods, coarser
# further out. None = entire history.
PERIOD_OPTIONS = [1, 3, 7, 14, 30, 60, 90, 180, 365, None]
TIMER_OPTIONS = {None, 15, 30, 60}

# --- Scoring, all chef-configurable per room (defaults below) ---------------
# points_correct: base reward for a correct guess. A single pick pays this
# once; a multi-select pick pays this per correct player *only if every pick
# in the selection is correct* (one wrong pick fails the whole vote and costs
# half this amount per wrong pick instead).
DEFAULT_POINTS_CORRECT = 50
# points_owner_miss: automatic, no-risk bonus paid to the video's owner(s)
# per voter who didn't identify them. Always applies, no opt-in needed.
DEFAULT_POINTS_OWNER_MISS = 75
# bet_multiplier: shared risk/reward scaler for both bet types below. Betting
# multiplies the normal payout if you're right, and costs you points if
# you're wrong (instead of the usual "wrong = 0" outcome).
DEFAULT_BET_MULTIPLIER = 2.0
# bet_quota_percent: caps how many bets (owner-bets + guess-bets combined)
# each player can place in a single game, as a percentage of num_rounds
# (rounded up, minimum 1) — otherwise nothing stops someone from betting
# every single round.
DEFAULT_BET_QUOTA_PERCENT = 30

POINTS_RANGE = (10, 500)
BET_MULTIPLIER_RANGE = (1.0, 5.0)
BET_QUOTA_PERCENT_RANGE = (0, 100)

# How many dead/unavailable videos we'll skip past in a row before giving up
# on drawing a round.
MAX_AVAILABILITY_ATTEMPTS = 8

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
        self.points_correct = DEFAULT_POINTS_CORRECT
        self.points_owner_miss = DEFAULT_POINTS_OWNER_MISS
        self.bet_multiplier = DEFAULT_BET_MULTIPLIER
        self.bet_quota_percent = DEFAULT_BET_QUOTA_PERCENT
        self.player_ids = []  # join order
        self.scores = {}
        self.bets_used = {}  # user_id -> number of bets spent this game (shared pool, both kinds)
        self.current_round = 0
        self.used_links = set()
        self.featured_counts = {}  # user_id -> number of rounds they've been the owner of, this game
        # Current round state
        self.round_video = None  # {"link":..., "liked_at":...}
        self.round_owners = set()  # user_ids who actually liked the video (can be several)
        self.round_voters = set()  # player_ids allowed/expected to vote this round (owners excluded)
        self.round_votes = {}  # voter_id -> set(guessed_user_ids)
        self.round_vote_bets = set()  # voter_ids who bet on their own guess this round
        self.round_owner_bets = set()  # owner_ids who bet on themselves this round
        self.round_status = None  # None | voting | revealed
        self.round_started_at = None
        self.last_result = None  # {"owner_ids":[...], "votes":[...], "bonuses":[...]}
        self.lock = threading.RLock()

    def add_player(self, user_id):
        if user_id not in self.player_ids:
            self.player_ids.append(user_id)
            self.scores[user_id] = 0
            self.bets_used[user_id] = 0

    def bet_quota(self):
        return max(1, math.ceil(self.num_rounds * self.bet_quota_percent / 100))

    def bets_remaining(self, user_id):
        if self.bet_quota_percent <= 0:
            return 0
        return max(0, self.bet_quota() - self.bets_used.get(user_id, 0))

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
                        "bets_remaining": self.bets_remaining(uid),
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
                    "has_owner_bet": current_user_id in self.round_owner_bets,
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
                    "points_correct": self.points_correct,
                    "points_owner_miss": self.points_owner_miss,
                    "bet_multiplier": self.bet_multiplier,
                    "bet_quota_percent": self.bet_quota_percent,
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


def update_config(
    room,
    chef_id,
    num_rounds,
    period_days,
    timer_seconds,
    points_correct=None,
    points_owner_miss=None,
    bet_multiplier=None,
    bet_quota_percent=None,
):
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

    if points_correct is None:
        points_correct = room.points_correct
    if points_owner_miss is None:
        points_owner_miss = room.points_owner_miss
    if bet_multiplier is None:
        bet_multiplier = room.bet_multiplier
    if bet_quota_percent is None:
        bet_quota_percent = room.bet_quota_percent

    if not isinstance(points_correct, int) or not (POINTS_RANGE[0] <= points_correct <= POINTS_RANGE[1]):
        return f"Points par bonne réponse : entier entre {POINTS_RANGE[0]} et {POINTS_RANGE[1]}"
    if not isinstance(points_owner_miss, int) or not (POINTS_RANGE[0] <= points_owner_miss <= POINTS_RANGE[1]):
        return f"Points par joueur qui ne trouve pas : entier entre {POINTS_RANGE[0]} et {POINTS_RANGE[1]}"
    try:
        bet_multiplier = float(bet_multiplier)
    except (TypeError, ValueError):
        return "Multiplicateur de pari invalide"
    if not (BET_MULTIPLIER_RANGE[0] <= bet_multiplier <= BET_MULTIPLIER_RANGE[1]):
        return f"Multiplicateur de pari : entre {BET_MULTIPLIER_RANGE[0]} et {BET_MULTIPLIER_RANGE[1]}"
    if not isinstance(bet_quota_percent, int) or not (
        BET_QUOTA_PERCENT_RANGE[0] <= bet_quota_percent <= BET_QUOTA_PERCENT_RANGE[1]
    ):
        return f"Quota de paris : entier entre {BET_QUOTA_PERCENT_RANGE[0]} et {BET_QUOTA_PERCENT_RANGE[1]} (%)"

    with room.lock:
        room.num_rounds = num_rounds
        room.period_days = period_days
        room.timer_seconds = timer_seconds
        room.points_correct = points_correct
        room.points_owner_miss = points_owner_miss
        room.bet_multiplier = bet_multiplier
        room.bet_quota_percent = bet_quota_percent
    return None


def _parse_liked_at(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _link_owners(room):
    """Every video liked by at least one player in the room (entire history),
    with the full set of players who liked it.

    Period filtering is applied here rather than in the DB query, and it's
    anchored to the *most recent liked video across the whole room* rather
    than to today's real-world date. Otherwise "last 2 weeks" would return
    nothing at all for a group whose most recent TikTok export is a few
    weeks stale — the filter is meant to mean "recent for this group", not
    "recent since the moment you happen to be playing".
    """
    link_owners = {}
    link_info = {}
    for uid in room.player_ids:
        for item in videos.get_links(uid):
            link_owners.setdefault(item["link"], set()).add(uid)
            link_info[item["link"]] = item

    if room.period_days is not None and link_info:
        dates = [_parse_liked_at(item["liked_at"]) for item in link_info.values()]
        dates = [d for d in dates if d is not None]
        if dates:
            anchor = max(dates)
            cutoff = anchor - timedelta(days=room.period_days)
            kept_links = {
                link
                for link, item in link_info.items()
                if (d := _parse_liked_at(item["liked_at"])) is not None and d >= cutoff
            }
            link_owners = {link: owners for link, owners in link_owners.items() if link in kept_links}
            link_info = {link: item for link, item in link_info.items() if link in kept_links}

    return link_owners, link_info


def _pool_by_owner(room):
    """Videos not drawn yet this game, grouped by each of their owners,
    excluding any video liked by literally every player in the room (nobody
    would be left to vote on it).

    Grouping by owner first (rather than a flat list of every video) is what
    makes the draw below fair: a player who liked 5000 videos and one who
    liked 50 both get an equal chance of being featured in a round, instead
    of the prolific liker dominating a flat random pick.
    """
    link_owners, link_info = _link_owners(room)

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

    for _attempt in range(MAX_AVAILABILITY_ATTEMPTS):
        if not by_owner:
            return False

        # Fair draw: among players who still have an eligible video, pick one
        # of those featured the *fewest* times so far this game (ties broken
        # randomly), then pick uniformly among their videos. Over a full game
        # this splits rounds as evenly as possible across everyone, instead of
        # just being unbiased on any single round.
        candidates = list(by_owner.keys())
        min_count = min(room.featured_counts.get(uid, 0) for uid in candidates)
        least_featured = [uid for uid in candidates if room.featured_counts.get(uid, 0) == min_count]
        owner_id = random.choice(least_featured)
        chosen = random.choice(by_owner[owner_id])

        if availability.is_available(chosen["link"]):
            room.round_video = {"link": chosen["link"], "liked_at": chosen["liked_at"]}
            room.round_owners = chosen["owners"]
            room.round_voters = set(room.player_ids) - room.round_owners
            room.round_votes = {}
            room.round_vote_bets = set()
            room.round_owner_bets = set()
            room.round_status = "voting"
            room.round_started_at = time.time()
            room.last_result = None
            room.used_links.add(chosen["link"])
            for oid in room.round_owners:
                room.featured_counts[oid] = room.featured_counts.get(oid, 0) + 1
            return True

        # Dead video (deleted/private/unavailable): exclude it for good and
        # try again with whatever's left.
        room.used_links.add(chosen["link"])
        by_owner[owner_id] = [v for v in by_owner[owner_id] if v["link"] != chosen["link"]]
        if not by_owner[owner_id]:
            del by_owner[owner_id]

    return False


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


def _score_vote(room, guesses, owners, used_bet):
    """Correct single guess pays points_correct (x bet_multiplier and at risk
    of an equal loss if betting). Multi-select pays points_correct per correct
    pick if the whole selection is right, otherwise half that per wrong pick
    (no betting on multi-select — the risk is already built in)."""
    if len(guesses) == 1:
        correct = guesses <= owners
        if used_bet:
            return room.points_correct * room.bet_multiplier if correct else -room.points_correct * room.bet_multiplier
        return room.points_correct if correct else 0
    wrong = guesses - owners
    if wrong:
        return -(room.points_correct / 2) * len(wrong)
    correct = guesses & owners
    return room.points_correct * len(correct)


def _reveal(room):
    if room.round_status != "voting":
        return
    owners = room.round_owners

    votes_result = []
    for voter_id in room.round_voters:
        guesses = room.round_votes.get(voter_id, set())
        used_bet = voter_id in room.round_vote_bets
        points = _score_vote(room, guesses, owners, used_bet) if guesses else 0
        if points:
            room.scores[voter_id] = room.scores.get(voter_id, 0) + points
        votes_result.append(
            {
                "voter_id": voter_id,
                "guessed_user_ids": sorted(guesses),
                "points": points,
                "used_bet": used_bet,
            }
        )

    # Owner payout: automatic no-risk bonus by default, or a bigger-upside /
    # real-downside bet if the owner opted in this round.
    bonuses_result = []
    for owner_id in owners:
        found_by = sum(1 for uid in room.round_voters if owner_id in room.round_votes.get(uid, set()))
        missed_by = max(0, len(room.round_voters) - found_by)
        used_bet = owner_id in room.round_owner_bets
        if used_bet:
            if missed_by > 0:
                bonus = room.points_owner_miss * room.bet_multiplier * missed_by
            else:
                bonus = -room.points_owner_miss * room.bet_multiplier
        else:
            bonus = room.points_owner_miss * missed_by
        if bonus:
            room.scores[owner_id] = room.scores.get(owner_id, 0) + bonus
        bonuses_result.append(
            {"owner_id": owner_id, "missed_by": missed_by, "bonus": bonus, "used_bet": used_bet}
        )

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


def submit_vote(room, voter_id, guessed_user_ids, use_bet=False):
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
        if use_bet:
            if len(guesses) != 1:
                return "Le pari n'est possible que pour un choix unique"
            if room.bets_remaining(voter_id) <= 0:
                return "Plus de paris disponibles pour cette partie"
        room.round_votes[voter_id] = guesses
        if use_bet:
            room.round_vote_bets.add(voter_id)
            room.bets_used[voter_id] = room.bets_used.get(voter_id, 0) + 1
        if len(room.round_votes) >= len(room.round_voters):
            _reveal(room)
    return None


def place_owner_bet(room, owner_id):
    if room.status != "in_progress":
        return "La partie n'est pas en cours"
    with room.lock:
        _maybe_expire_timer(room)
        if room.round_status != "voting":
            return "Trop tard pour parier sur ce round"
        if owner_id not in room.round_owners:
            return "Tu n'es pas propriétaire de la vidéo de ce round"
        if owner_id in room.round_owner_bets:
            return "Tu as déjà parié sur ce round"
        if room.bets_remaining(owner_id) <= 0:
            return "Plus de paris disponibles pour cette partie"
        room.round_owner_bets.add(owner_id)
        room.bets_used[owner_id] = room.bets_used.get(owner_id, 0) + 1
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
        room.featured_counts = {}
        room.scores = {uid: 0 for uid in room.player_ids}
        room.bets_used = {uid: 0 for uid in room.player_ids}
        room.round_video = None
        room.round_owners = set()
        room.round_voters = set()
        room.round_votes = {}
        room.round_vote_bets = set()
        room.round_owner_bets = set()
        room.round_status = None
        room.round_started_at = None
        room.last_result = None
    return None
