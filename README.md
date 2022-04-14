# tidal to spotify

This repo contains quick and dirty scripts to semi-automatically transfer
artists and playlsits from tidal to spotify. It assumes we have already
downloaded all artists and playlists as json. This can for example be done by
looking at the network calls from tidal when selecting the artists or
playlists. Each page is handled as an element in a list within one single json.

[spotipy](https://spotipy.readthedocs.io/en/2.19.0/) is used to access to
spotify API. See their documentation on how to specify credentials.

Most likely all tracks from tidal are not found through the spotify search. The
search for tracks are based on artist and song title, these are not unique and
might be written differently across the platforms. A json is written to stdout
containing information on which tidal tracks were added toa  playlist and which
were not.

There will most likely be cases where a specific version of a track from tidal
is replaced by another version in spotify.

NOTE: This is a one off for me to convert my tidal music collection to spotify.
The scripts have rudimentary logging, but are not written with future
maintainence in mind.
