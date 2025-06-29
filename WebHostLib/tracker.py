import datetime
import collections
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, NamedTuple, Counter
from uuid import UUID
from email.utils import parsedate_to_datetime

from flask import make_response, render_template, request, Request, Response
from werkzeug.exceptions import abort

from MultiServer import Context, get_saving_second
from NetUtils import ClientStatus, Hint, NetworkItem, NetworkSlot, SlotType
from Utils import restricted_loads, KeyedDefaultDict
from . import app, cache
from .models import GameDataPackage, Room

# Multisave is currently updated, at most, every minute.
TRACKER_CACHE_TIMEOUT_IN_SECONDS = 60

_multidata_cache = {}
_multiworld_trackers: Dict[str, Callable] = {}
_player_trackers: Dict[str, Callable] = {}

TeamPlayer = Tuple[int, int]
ItemMetadata = Tuple[int, int, int]


def _cache_results(func: Callable) -> Callable:
    """Stores the results of any computationally expensive methods after the initial call in TrackerData.
    If called again, returns the cached result instead, as results will not change for the lifetime of TrackerData.
    """
    def method_wrapper(self: "TrackerData", *args):
        cache_key = f"{func.__name__}{''.join(f'_[{arg.__repr__()}]' for arg in args)}"
        if cache_key in self._tracker_cache:
            return self._tracker_cache[cache_key]

        result = func(self, *args)
        self._tracker_cache[cache_key] = result
        return result

    return method_wrapper


@dataclass
class TrackerData:
    """A helper dataclass that is instantiated each time an HTTP request comes in for tracker data.

    Provides helper methods to lazily load necessary data that each tracker require and caches any results so any
    subsequent helper method calls do not need to recompute results during the lifetime of this instance.
    """
    room: Room
    _multidata: Dict[str, Any]
    _multisave: Dict[str, Any]
    _tracker_cache: Dict[str, Any]

    def __init__(self, room: Room):
        """Initialize a new RoomMultidata object for the current room."""
        self.room = room
        self._multidata = Context.decompress(room.seed.multidata)
        self._multisave = restricted_loads(room.multisave) if room.multisave else {}
        self._tracker_cache = {}

        self.item_name_to_id: Dict[str, Dict[str, int]] = {}
        self.location_name_to_id: Dict[str, Dict[str, int]] = {}

        # Generate inverse lookup tables from data package, useful for trackers.
        self.item_id_to_name: Dict[str, Dict[int, str]] = KeyedDefaultDict(lambda game_name: {
            game_name: KeyedDefaultDict(lambda code: f"Unknown Game {game_name} - Item (ID: {code})")
        })
        self.location_id_to_name: Dict[str, Dict[int, str]] = KeyedDefaultDict(lambda game_name: {
            game_name: KeyedDefaultDict(lambda code: f"Unknown Game {game_name} - Location (ID: {code})")
        })
        for game, game_package in self._multidata["datapackage"].items():
            game_package = restricted_loads(GameDataPackage.get(checksum=game_package["checksum"]).data)
            self.item_id_to_name[game] = KeyedDefaultDict(lambda code: f"Unknown Item (ID: {code})", {
                id: name for name, id in game_package["item_name_to_id"].items()})
            self.location_id_to_name[game] = KeyedDefaultDict(lambda code: f"Unknown Location (ID: {code})", {
                id: name for name, id in game_package["location_name_to_id"].items()})

            # Normal lookup tables as well.
            self.item_name_to_id[game] = game_package["item_name_to_id"]
            self.location_name_to_id[game] = game_package["location_name_to_id"]

    def get_seed_name(self) -> str:
        """Retrieves the seed name."""
        return self._multidata["seed_name"]

    def get_slot_data(self, team: int, player: int) -> Dict[str, Any]:
        """Retrieves the slot data for a given player."""
        return self._multidata["slot_data"][player]

    def get_slot_info(self, team: int, player: int) -> NetworkSlot:
        """Retrieves the NetworkSlot data for a given player."""
        return self._multidata["slot_info"][player]

    def get_player_name(self, team: int, player: int) -> str:
        """Retrieves the slot name for a given player."""
        return self.get_slot_info(team, player).name

    def get_player_game(self, team: int, player: int) -> str:
        """Retrieves the game for a given player."""
        return self.get_slot_info(team, player).game

    def get_player_locations(self, team: int, player: int) -> Dict[int, ItemMetadata]:
        """Retrieves all locations with their containing item's metadata for a given player."""
        return self._multidata["locations"][player]

    def get_player_starting_inventory(self, team: int, player: int) -> List[int]:
        """Retrieves a list of all item codes a given slot starts with."""
        return self._multidata["precollected_items"][player]

    def get_player_checked_locations(self, team: int, player: int) -> Set[int]:
        """Retrieves the set of all locations marked complete by this player."""
        return self._multisave.get("location_checks", {}).get((team, player), set())

    @_cache_results
    def get_player_missing_locations(self, team: int, player: int) -> Set[int]:
        """Retrieves the set of all locations not marked complete by this player."""
        return set(self.get_player_locations(team, player)) - self.get_player_checked_locations(team, player)

    def get_player_received_items(self, team: int, player: int) -> List[NetworkItem]:
        """Returns all items received to this player in order of received."""
        return self._multisave.get("received_items", {}).get((team, player, True), [])

    @_cache_results
    def get_player_inventory_counts(self, team: int, player: int) -> collections.Counter:
        """Retrieves a dictionary of all items received by their id and their received count."""
        received_items = self.get_player_received_items(team, player)
        starting_items = self.get_player_starting_inventory(team, player)
        inventory = collections.Counter()
        for item in received_items:
            inventory[item.item] += 1
        for item in starting_items:
            inventory[item] += 1

        return inventory

    @_cache_results
    def get_player_hints(self, team: int, player: int) -> Set[Hint]:
        """Retrieves a set of all hints relevant for a particular player."""
        return self._multisave.get("hints", {}).get((team, player), set())

    @_cache_results
    def get_player_last_activity(self, team: int, player: int) -> Optional[datetime.timedelta]:
        """Retrieves the relative timedelta for when a particular player was last active.
        Returns None if no activity was ever recorded.
        """
        return self.get_room_last_activity().get((team, player), None)

    def get_player_client_status(self, team: int, player: int) -> ClientStatus:
        """Retrieves the ClientStatus of a particular player."""
        return self._multisave.get("client_game_state", {}).get((team, player), ClientStatus.CLIENT_UNKNOWN)

    def get_player_alias(self, team: int, player: int) -> Optional[str]:
        """Returns the alias of a particular player, if any."""
        return self._multisave.get("name_aliases", {}).get((team, player), None)

    @_cache_results
    def get_team_completed_worlds_count(self) -> Dict[int, int]:
        """Retrieves a dictionary of number of completed worlds per team."""
        return {
            team: sum(
                self.get_player_client_status(team, player) == ClientStatus.CLIENT_GOAL for player in players
            ) for team, players in self.get_all_players().items()
        }

    @_cache_results
    def get_team_hints(self) -> Dict[int, Set[Hint]]:
        """Retrieves a dictionary of all hints per team."""
        hints = {}
        for team, players in self.get_all_slots().items():
            hints[team] = set()
            for player in players:
                hints[team] |= self.get_player_hints(team, player)

        return hints

    @_cache_results
    def get_team_locations_total_count(self) -> Dict[int, int]:
        """Retrieves a dictionary of total player locations each team has."""
        return {
            team: sum(len(self.get_player_locations(team, player)) for player in players)
            for team, players in self.get_all_players().items()
        }

    @_cache_results
    def get_team_locations_checked_count(self) -> Dict[int, int]:
        """Retrieves a dictionary of checked player locations each team has."""
        return {
            team: sum(len(self.get_player_checked_locations(team, player)) for player in players)
            for team, players in self.get_all_players().items()
        }

    # TODO: Change this method to properly build for each team once teams are properly implemented, as they don't
    #       currently exist in multidata to easily look up, so these are all assuming only 1 team: Team #0
    @_cache_results
    def get_all_slots(self) -> Dict[int, List[int]]:
        """Retrieves a dictionary of all players ids on each team."""
        return {
            0: [
                player for player, slot_info in self._multidata["slot_info"].items()
            ]
        }

    # TODO: Change this method to properly build for each team once teams are properly implemented, as they don't
    #       currently exist in multidata to easily look up, so these are all assuming only 1 team: Team #0
    @_cache_results
    def get_all_players(self) -> Dict[int, List[int]]:
        """Retrieves a dictionary of all player slot-type players ids on each team."""
        return {
            0: [
                player for player, slot_info in self._multidata["slot_info"].items()
                if self.get_slot_info(0, player).type == SlotType.player
            ]
        }

    @_cache_results
    def get_room_saving_second(self) -> int:
        """Retrieves the saving second value for this seed.

        Useful for knowing when the multisave gets updated so trackers can attempt to update.
        """
        return get_saving_second(self.get_seed_name())

    @_cache_results
    def get_room_locations(self) -> Dict[TeamPlayer, Dict[int, ItemMetadata]]:
        """Retrieves a dictionary of all locations and their associated item metadata per player."""
        return {
            (team, player): self.get_player_locations(team, player)
            for team, players in self.get_all_players().items() for player in players
        }

    @_cache_results
    def get_room_games(self) -> Dict[TeamPlayer, str]:
        """Retrieves a dictionary of games for each player."""
        return {
            (team, player): self.get_player_game(team, player)
            for team, players in self.get_all_slots().items() for player in players
        }

    @_cache_results
    def get_room_locations_complete(self) -> Dict[TeamPlayer, int]:
        """Retrieves a dictionary of all locations complete per player."""
        return {
            (team, player): len(self.get_player_checked_locations(team, player))
            for team, players in self.get_all_players().items() for player in players
        }

    @_cache_results
    def get_room_client_statuses(self) -> Dict[TeamPlayer, ClientStatus]:
        """Retrieves a dictionary of all ClientStatus values per player."""
        return {
            (team, player): self.get_player_client_status(team, player)
            for team, players in self.get_all_players().items() for player in players
        }

    @_cache_results
    def get_room_long_player_names(self) -> Dict[TeamPlayer, str]:
        """Retrieves a dictionary of names with aliases for each player."""
        long_player_names = {}
        for team, players in self.get_all_slots().items():
            for player in players:
                alias = self.get_player_alias(team, player)
                if alias:
                    long_player_names[team, player] = f"{alias} ({self.get_player_name(team, player)})"
                else:
                    long_player_names[team, player] = self.get_player_name(team, player)

        return long_player_names

    @_cache_results
    def get_room_last_activity(self) -> Dict[TeamPlayer, datetime.timedelta]:
        """Retrieves a dictionary of all players and the timedelta from now to their last activity.
        Does not include players who have no activity recorded.
        """
        last_activity: Dict[TeamPlayer, datetime.timedelta] = {}
        now = datetime.datetime.utcnow()
        for (team, player), timestamp in self._multisave.get("client_activity_timers", []):
            last_activity[team, player] = now - datetime.datetime.utcfromtimestamp(timestamp)

        return last_activity

    @_cache_results
    def get_room_videos(self) -> Dict[TeamPlayer, Tuple[str, str]]:
        """Retrieves a dictionary of any players who have video streaming enabled and their feeds.

        Only supported platforms are Twitch and YouTube.
        """
        video_feeds = {}
        for (team, player), video_data in self._multisave.get("video", []):
            video_feeds[team, player] = video_data

        return video_feeds

    @_cache_results
    def get_spheres(self) -> List[List[int]]:
        """ each sphere is { player: { location_id, ... } } """
        return self._multidata.get("spheres", [])


def _process_if_request_valid(incoming_request: Request, room: Optional[Room]) -> Optional[Response]:
    if not room:
        abort(404)

    if_modified_str: Optional[str] = incoming_request.headers.get("If-Modified-Since", None)
    if if_modified_str:
        if_modified = parsedate_to_datetime(if_modified_str)
        if if_modified.tzinfo is None:
            abort(400)  # standard requires "GMT" timezone
        # database may use datetime.utcnow(), which is timezone-naive. convert to timezone-aware.
        last_activity = room.last_activity
        if last_activity.tzinfo is None:
            last_activity = room.last_activity.replace(tzinfo=datetime.timezone.utc)
        # if_modified has less precision than last_activity, so we bring them to same precision
        if if_modified >= last_activity.replace(microsecond=0):
            return make_response("",  304)

    return None


@app.route("/tracker/<suuid:tracker>/<int:tracked_team>/<int:tracked_player>")
def get_player_tracker(tracker: UUID, tracked_team: int, tracked_player: int, generic: bool = False) -> Response:
    key = f"{tracker}_{tracked_team}_{tracked_player}_{generic}"
    response: Optional[Response] = cache.get(key)
    if response:
        return response

    # Room must exist.
    room = Room.get(tracker=tracker)

    response = _process_if_request_valid(request, room)
    if response:
        return response

    timeout, last_modified, tracker_page = get_timeout_and_player_tracker(room, tracked_team, tracked_player, generic)
    response = make_response(tracker_page)
    response.last_modified = last_modified
    cache.set(key, response, timeout)
    return response


def get_timeout_and_player_tracker(room: Room, tracked_team: int, tracked_player: int, generic: bool)\
        -> Tuple[int, datetime.datetime, str]:
    tracker_data = TrackerData(room)

    # Load and render the game-specific player tracker, or fallback to generic tracker if none exists.
    game_specific_tracker = _player_trackers.get(tracker_data.get_player_game(tracked_team, tracked_player), None)
    if game_specific_tracker and not generic:
        tracker = game_specific_tracker(tracker_data, tracked_team, tracked_player)
    else:
        tracker = render_generic_tracker(tracker_data, tracked_team, tracked_player)

    return ((tracker_data.get_room_saving_second() - datetime.datetime.now().second)
            % TRACKER_CACHE_TIMEOUT_IN_SECONDS or TRACKER_CACHE_TIMEOUT_IN_SECONDS, room.last_activity, tracker)


@app.route("/generic_tracker/<suuid:tracker>/<int:tracked_team>/<int:tracked_player>")
def get_generic_game_tracker(tracker: UUID, tracked_team: int, tracked_player: int) -> Response:
    return get_player_tracker(tracker, tracked_team, tracked_player, True)


@app.route("/tracker/<suuid:tracker>", defaults={"game": "Generic"})
@app.route("/tracker/<suuid:tracker>/<game>")
def get_multiworld_tracker(tracker: UUID, game: str) -> Response:
    key = f"{tracker}_{game}"
    response: Optional[Response] = cache.get(key)
    if response:
        return response

    # Room must exist.
    room = Room.get(tracker=tracker)

    response = _process_if_request_valid(request, room)
    if response:
        return response

    timeout, last_modified, tracker_page = get_timeout_and_multiworld_tracker(room, game)
    response = make_response(tracker_page)
    response.last_modified = last_modified
    cache.set(key, response, timeout)
    return response


def get_timeout_and_multiworld_tracker(room: Room, game: str)\
        -> Tuple[int, datetime.datetime, str]:
    tracker_data = TrackerData(room)
    enabled_trackers = list(get_enabled_multiworld_trackers(room).keys())
    if game in _multiworld_trackers:
        tracker = _multiworld_trackers[game](tracker_data, enabled_trackers)
    else:
        tracker = render_generic_multiworld_tracker(tracker_data, enabled_trackers)

    return ((tracker_data.get_room_saving_second() - datetime.datetime.now().second)
            % TRACKER_CACHE_TIMEOUT_IN_SECONDS or TRACKER_CACHE_TIMEOUT_IN_SECONDS, room.last_activity, tracker)


def get_enabled_multiworld_trackers(room: Room) -> Dict[str, Callable]:
    # Render the multitracker for any games that exist in the current room if they are defined.
    enabled_trackers = {}
    for game_name, endpoint in _multiworld_trackers.items():
        if any(slot.game == game_name for slot in room.seed.slots):
            enabled_trackers[game_name] = endpoint

    # We resort the tracker to have Generic first, then lexicographically each enabled game.
    return {
        "Generic": render_generic_multiworld_tracker,
        **{key: enabled_trackers[key] for key in sorted(enabled_trackers.keys())},
    }


def render_generic_tracker(tracker_data: TrackerData, team: int, player: int) -> str:
    game = tracker_data.get_player_game(team, player)

    received_items_in_order = {}
    starting_inventory = tracker_data.get_player_starting_inventory(team, player)
    for index, item in enumerate(starting_inventory):
        received_items_in_order[item] = index
    for index, network_item in enumerate(tracker_data.get_player_received_items(team, player),
                                         start=len(starting_inventory)):
        received_items_in_order[network_item.item] = index

    return render_template(
        template_name_or_list="genericTracker.html",
        game_specific_tracker=game in _player_trackers,
        room=tracker_data.room,
        get_slot_info=tracker_data.get_slot_info,
        team=team,
        player=player,
        player_name=tracker_data.get_room_long_player_names()[team, player],
        inventory=tracker_data.get_player_inventory_counts(team, player),
        locations=tracker_data.get_player_locations(team, player),
        checked_locations=tracker_data.get_player_checked_locations(team, player),
        received_items=received_items_in_order,
        saving_second=tracker_data.get_room_saving_second(),
        game=game,
        games=tracker_data.get_room_games(),
        player_names_with_alias=tracker_data.get_room_long_player_names(),
        location_id_to_name=tracker_data.location_id_to_name,
        item_id_to_name=tracker_data.item_id_to_name,
        hints=tracker_data.get_player_hints(team, player),
    )


def render_generic_multiworld_tracker(tracker_data: TrackerData, enabled_trackers: List[str]) -> str:
    return render_template(
        "multitracker.html",
        enabled_trackers=enabled_trackers,
        current_tracker="Generic",
        room=tracker_data.room,
        get_slot_info=tracker_data.get_slot_info,
        all_slots=tracker_data.get_all_slots(),
        room_players=tracker_data.get_all_players(),
        locations=tracker_data.get_room_locations(),
        locations_complete=tracker_data.get_room_locations_complete(),
        total_team_locations=tracker_data.get_team_locations_total_count(),
        total_team_locations_complete=tracker_data.get_team_locations_checked_count(),
        player_names_with_alias=tracker_data.get_room_long_player_names(),
        completed_worlds=tracker_data.get_team_completed_worlds_count(),
        games=tracker_data.get_room_games(),
        states=tracker_data.get_room_client_statuses(),
        hints=tracker_data.get_team_hints(),
        activity_timers=tracker_data.get_room_last_activity(),
        videos=tracker_data.get_room_videos(),
        item_id_to_name=tracker_data.item_id_to_name,
        location_id_to_name=tracker_data.location_id_to_name,
        saving_second=tracker_data.get_room_saving_second(),
    )


def render_generic_multiworld_sphere_tracker(tracker_data: TrackerData) -> str:
    return render_template(
        "multispheretracker.html",
        room=tracker_data.room,
        tracker_data=tracker_data,
    )


@app.route("/sphere_tracker/<suuid:tracker>")
@cache.memoize(timeout=TRACKER_CACHE_TIMEOUT_IN_SECONDS)
def get_multiworld_sphere_tracker(tracker: UUID):
    # Room must exist.
    room = Room.get(tracker=tracker)
    if not room:
        abort(404)

    tracker_data = TrackerData(room)
    return render_generic_multiworld_sphere_tracker(tracker_data)


# TODO: This is a temporary solution until a proper Tracker API can be implemented for tracker templates and data to
#       live in their respective world folders.

from worlds import network_data_package


    