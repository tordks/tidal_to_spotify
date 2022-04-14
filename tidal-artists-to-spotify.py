import json

from loguru import logger
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# TODO: write as click script
# TODO: refactor nicely

user = "kriznik"
tidal_artists_path = "tidal_artists.json"

scope = "user-follow-modify"
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(scope=scope))


with open(tidal_artists_path) as fp:
    tidal_artists = json.load(fp)["items"]

artists_to_follow = []
for tidal_artist in tidal_artists:
    # Search for artist
    artist_name = tidal_artist["item"]["name"]
    response = sp.search(artist_name, type="artist")

    # search for artists with the current artist name
    artists = []
    for artist in response["artists"]["items"]:
        if artist["name"].lower() == artist_name.lower():
            artists.append(artist)

    # Handle that aritst name is non-unique
    if len(artists) == 1:
        artists_to_follow.append(artists[0])
    elif len(artists) > 1:
        logger.info(f"multiple artists found for artist name {artist_name}")
        for i, artist in enumerate(artists):
            print(
                i,
                artist["name"],
                artist["followers"]["total"],
                artist["external_urls"]["spotify"],
            )
        artist_idx = int(input("Which artist to choose? "))
        logger.info(
            f"selected artist {artist_idx} {artist['name']} {artist['id']}"
        )
        artists_to_follow.append(artists[artist_idx])
    else:
        logger.warning(f"No artists found for artist name: {artist_name}")


# follow artists
logger.info(f"Follow  {len(artists_to_follow)} artists")
response = sp.user_follow_artists(
    [artist["id"] for artist in artists_to_follow]
)
