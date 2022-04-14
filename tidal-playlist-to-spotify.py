# TODO: refactor for readability.
#    * proper CLI instead of global vars
#    * track and track_scores into named tuples
#    * extract functions
# TODO: option to ask for user input for tracks that did not find a good enough
#       match.

from collections import defaultdict
from functools import reduce
import json
from pathlib import Path
import re

from loguru import logger
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from rapidfuzz.fuzz import ratio, partial_ratio

# Input params
USER = "kriznik"
TIDAL_PLAYLIST_DIR = Path("tidal_playlists")
THRESHOLDS = (60, 60, 40)  # title, artist, album
CREATE_PLAYLIST_IF_IT_EXISTS = False
# SCORER = ratio
SCORER = partial_ratio
# Check the score of top N tracks
CHECK_N_TRACKS = 30
# A dry run does not create any playlists
DRYRUN = False


def playlist_name_exists(sp, playlist_name):
    existing_playlists = sp.user_playlists(USER)["items"]
    for playlist in existing_playlists:
        if playlist_name == playlist["name"]:
            return True
    else:
        return False


def load_tidal_playlist_tracks(playlist_path):
    with open(playlist_path) as fp:
        # json contains list of pages of tracks within the playlist
        playlist_tracks = json.load(fp)

        # combine pages of the tidal playlist.
        playlist_tracks = reduce(
            lambda x, y: x + y, [tracks["items"] for tracks in playlist_tracks]
        )
    return playlist_tracks


def search_spotify_tracks(sp, song_title, artist_name, limit=50):
    paranthesis_removed = False
    while True:
        tracks = sp.search(
            f"{song_title} {artist_name}",
            type="track",
            limit=limit,
        )["tracks"]["items"]
        # NOTE: sometimes tracks return as None from the search.
        tracks = [track for track in tracks if track is not None]

        # TODO: if result is empty, attempt:
        #    * remove everything after '-' from song title
        #    * If there is an '&' in artist name there are multiple artist. Try
        #      to search for only first artist.
        #    * If there is an '&' in artist name there are multiple artist. Try
        #      replacing '&' with 'and'.

        # Sometimes tracks have a long description in paranthesis that hinders track
        # discovery. Try and remove last paranthesis paranthesis.
        if len(tracks) == 0 and not paranthesis_removed:
            song_title_split = re.split("\(|\)|\[|\]", song_title)
            if len(song_title_split) == 1:
                break
            song_title = "".join(song_title_split[::2]).strip()
            paranthesis_removed = True
        else:
            break

    return tracks


def score_list(reference: str, to_score: list[str], scorer=ratio):
    """
    Get the score and index of the element in a list that matches the reference
    best.
    """
    score = -1
    idx = -1
    for element_idx, element in enumerate(to_score):
        temp_score = scorer(element.lower(), reference.lower())
        if temp_score > score:
            score = temp_score
            idx = element_idx
    return idx, score


def score_track_artist(artist, track, scorer):
    """
    One track might have many artists. Return the artist with the best score.
    """
    sp_artists = [sp_artist["name"] for sp_artist in track["artists"]]
    artist_idx, artist_score = score_list(artist, sp_artists, scorer)
    return artist_idx, artist_score


def score_spotify_track(track, title, artist, album, scorer=ratio):
    """
    Score how well track title, artist and album matches the given ones.
    """
    title_score = scorer(track["name"].lower(), title.lower())
    _, artist_score = score_track_artist(artist, track, scorer)
    album_score = scorer(track["album"]["name"].lower(), album.lower())
    return title_score, artist_score, album_score


def sort_on_scores(scores, tracks):
    """
    Sort tracks on first on song title score, then artist score and
    then album score.
    """
    # TODO: sorting can likely be improved. Currently one might miss a better
    # track if it's title matches better, but from a worse album. Ie. we might
    # miss a track with scores (95, 30, 60) if there is a  track that is (98,
    # 80, 60). Consider
    scores_tracks = list(zip(scores, tracks))
    scores_tracks.sort(key=lambda x: x[0][2], reverse=True)
    scores_tracks.sort(key=lambda x: x[0][1], reverse=True)
    scores_tracks.sort(key=lambda x: x[0][0], reverse=True)
    return zip(*scores_tracks)


def is_track_match(title_score, artist_score, album_score, thresholds):
    """
    Check if the track is a match based on it's scores.
    """
    match = False
    if (
        title_score > thresholds[0]
        and artist_score > thresholds[1]
        and album_score > thresholds[2]
    ):
        match = True
    elif title_score > thresholds[0] and artist_score > thresholds[1]:
        match = True
    return match


def create_playlist(sp, user, playlist_name, track_ids):
    sp_playlist = sp.user_playlist_create(user, playlist_name, public=False)

    # can only add 100 tracks at a time, hence batch it
    n_tracks = len(track_ids)
    batch_size = 100
    idx0 = 0
    idx1 = -1
    while idx0 < n_tracks:
        idx1 = idx0 + batch_size

        if idx1 > n_tracks:
            idx1 = n_tracks

        sp.user_playlist_add_tracks(
            user, sp_playlist["id"], track_ids[idx0:idx1]
        )
        idx0 = idx1


def main():
    scope = ["playlist-read-private", "playlist-modify-private"]
    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(scope=scope),
        requests_timeout=10,
        retries=3,
        status_retries=3,
    )

    tidal_playlist_paths = [
        path for path in TIDAL_PLAYLIST_DIR.iterdir() if path.suffix == ".json"
    ]

    sp_tracks_added = defaultdict(list)
    sp_tracks_not_added = defaultdict(list)
    for playlist_path in tidal_playlist_paths:
        playlist_name = playlist_path.stem.replace("-", " ")
        logger.info(f"Processing playlist '{playlist_name}'")

        logger.info("Check if playlist exists")
        if (
            playlist_name_exists(sp, playlist_name)
            and not CREATE_PLAYLIST_IF_IT_EXISTS
        ):
            logger.warning(
                "The playlist name already exists. Skipping creation of playlist"
            )
            continue

        try:
            logger.info("Load tracks from file")
            playlist_tracks = load_tidal_playlist_tracks(playlist_path)
        except Exception as err:
            logger.error(err)
            logger.error(
                f"Failed to load tracks for playlist '{playlist_name}'"
            )
            continue

        sp_track_ids = []
        logger.info("Search for tracks")
        for track in playlist_tracks:
            song_title = track["item"]["title"]
            artist_name = track["item"]["artist"]["name"]
            album_title = track["item"]["album"]["title"]

            sp_tracks = search_spotify_tracks(
                sp, song_title, artist_name, limit=50
            )

            if len(sp_tracks) == 0:
                logger.warning(
                    f"No tracks found for '{song_title}' '{artist_name}' '{album_title}'"
                )
                sp_tracks_not_added[playlist_name].append(
                    {
                        "title": song_title,
                        "artist": artist_name,
                        "album": album_title,
                        "best_track": None,
                        "best_score": None,
                    }
                )
                continue

            sp_track_scores = [
                score_spotify_track(
                    track, song_title, artist_name, album_title, scorer=SCORER
                )
                for track in sp_tracks
            ]

            sp_track_scores, sp_tracks = sort_on_scores(
                sp_track_scores, sp_tracks
            )

            sp_tracks = sp_tracks[:CHECK_N_TRACKS]
            sp_track_scores = sp_track_scores[:CHECK_N_TRACKS]

            # TODO: first check all with album threshold, then all without album
            # threshold. Currently each is tested with/without album threshold
            # in turn. Might be easiest to add numpy dependency.
            for best_track, best_score in zip(sp_tracks, sp_track_scores):
                title_score, artist_score, album_score = best_score

                if is_track_match(
                    title_score,
                    artist_score,
                    album_score,
                    THRESHOLDS,
                ):
                    sp_track_ids.append((best_track["id"]))
                    best_artist_idx, _ = score_track_artist(
                        artist_name, best_track, scorer=SCORER
                    )
                    best_artist = best_track["artists"][best_artist_idx]["name"]
                    sp_tracks_added[playlist_name].append(
                        {
                            "title": song_title,
                            "artist": artist_name,
                            "album": album_title,
                            "best_track": {
                                "title": best_track["name"],
                                "artist": best_artist,
                                "album": best_track["album"]["name"],
                            },
                            "best_score": best_score,
                        }
                    )
                    break
            else:
                # TODO: if no track is found, remove paranthesis from song_title and score again.
                logger.warning(
                    f"found no match above threshold for '{song_title}' '{artist_name}' '{album_title}'"
                )

                best_artist_idx, _ = score_track_artist(
                    artist_name, best_track, scorer=SCORER
                )
                best_artist = best_track["artists"][best_artist_idx]["name"]
                sp_tracks_not_added[playlist_name].append(
                    {
                        "title": song_title,
                        "artist": artist_name,
                        "album": album_title,
                        "best_track": {
                            "title": best_track["name"],
                            "artist": best_artist,
                            "album": best_track["album"]["name"],
                        },
                        "best_score": best_score,
                    }
                )

        logger.info(
            f"Create playlist '{playlist_name}' with {len(sp_track_ids)} of {len(playlist_tracks)} tracks"
        )

        if not DRYRUN:
            create_playlist(sp, USER, playlist_name, sp_track_ids)

    result = {
        "tracks_added": sp_tracks_added,
        "tracks_not_added": sp_tracks_not_added,
    }
    print(json.dumps(dict(result), indent=4, ensure_ascii=False))

    n_tracks_not_added = sum(
        [len(missing_tracks) for missing_tracks in sp_tracks_not_added.values()]
    )
    logger.info(f"{n_tracks_not_added} tracks not added")


if __name__ == "__main__":
    main()