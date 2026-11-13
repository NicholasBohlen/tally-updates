#!/usr/bin/env python3
"""The boards' Movies & TV list (2026-11-13): what's in theaters, what's new to stream, and the shows people are
watching, each with its genres, its rating, its age rating and where to watch it, from TMDB.

One key, the maker's, makes the list once a day (the update site's nightly job, .github/workflows/screen.yml in
tally-updates); every board reads the small file it writes, so no board carries a key.

    TMDB_API_KEY=... python3 tools/make_screen_list.py screen.json

TMDB_API_KEY: a TMDB API key (v3), or its read access token (v4, the long one). Only the standard library, so the
nightly job needs nothing installed. This product uses the TMDB API but is not endorsed or certified by TMDB.
"""
import datetime
import json
import os
import sys
import unicodedata
import urllib.parse
import urllib.request

API = "https://api.themoviedb.org/3"
REGION = "US"
COUNT = 10  # (each list: the board shows up to 8)
KEY = os.environ.get("TMDB_API_KEY", "").strip()


def get(path, **params):
    params.setdefault("language", "en-US")
    headers = {"Accept": "application/json", "User-Agent": "Tally scoreboard list (github.com/NicholasBohlen/tally-updates)"}
    if len(KEY) > 40:  # (the v4 read access token)
        headers["Authorization"] = "Bearer " + KEY
    else:
        params["api_key"] = KEY
    request = urllib.request.Request(API + path + "?" + urllib.parse.urlencode(params), headers=headers)
    with urllib.request.urlopen(request, timeout=30) as answer:
        return json.load(answer)


def plain(text):
    """The panel's letters: accents taken off ("Pokémon" -> "Pokemon"), curly quotes straightened, the rest kept."""
    text = (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-").replace("…", "...")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().strip()


def rating(item):
    """TMDB's score out of 10 (one place), when enough people have rated it to mean something."""
    if (item.get("vote_count") or 0) < 25 or not item.get("vote_average"):
        return None
    return round(float(item["vote_average"]), 1)


def provider(details):
    """Where to stream it in the region: the first subscription service, or the first place to rent or buy it."""
    found = ((details.get("watch/providers") or {}).get("results") or {}).get(REGION) or {}
    for kind in ("flatrate", "free", "ads", "rent", "buy"):
        if found.get(kind):
            return plain(found[kind][0].get("provider_name"))
    return ""


def movie_cert(details):
    """The age rating (PG-13): the region's theatrical one, else any it has."""
    for release_set in (details.get("release_dates") or {}).get("results") or []:
        if release_set.get("iso_3166_1") != REGION:
            continue
        dates = release_set.get("release_dates") or []
        for wanted in (3, 2, 4, 5, None):
            for one in dates:
                if one.get("certification") and (wanted is None or one.get("type") == wanted):
                    return one["certification"]
    return ""


def tv_cert(details):
    for one in (details.get("content_ratings") or {}).get("results") or []:
        if one.get("iso_3166_1") == REGION and one.get("rating"):
            return one["rating"]
    return ""


def movie(item, genres):
    details = get(f"/movie/{item['id']}", append_to_response="release_dates,watch/providers")
    out = {"title": plain(details.get("title") or item.get("title")), "year": (details.get("release_date") or "")[:4],
           "genres": [genres[g] for g in item.get("genre_ids", []) if g in genres][:2]}
    if rating(details) is not None:
        out["rating"] = rating(details)
    for key, value in (("cert", movie_cert(details)), ("where", provider(details)), ("runtime", details.get("runtime") or 0)):
        if value:
            out[key] = value
    return out


def show(item, genres):
    details = get(f"/tv/{item['id']}", append_to_response="content_ratings,watch/providers")
    out = {"title": plain(details.get("name") or item.get("name")), "genres": [genres[g] for g in item.get("genre_ids", []) if g in genres][:2]}
    if rating(details) is not None:
        out["rating"] = rating(details)
    where = provider(details) or plain(((details.get("networks") or [{}])[0]).get("name"))
    for key, value in (("cert", tv_cert(details)), ("where", where)):
        if value:
            out[key] = value
    upcoming = details.get("next_episode_to_air") or {}
    if upcoming.get("air_date"):
        out["next"] = {"date": upcoming["air_date"], "season": upcoming.get("season_number"), "episode": upcoming.get("episode_number")}
    return out


def short_genre(name):
    return {"Science Fiction": "Sci-Fi", "Sci-Fi & Fantasy": "Sci-Fi", "Action & Adventure": "Action", "War & Politics": "War"}.get(name, name)


def main():
    if not KEY:
        raise SystemExit("Set TMDB_API_KEY (a TMDB API key or read access token).")
    out_path = sys.argv[1] if len(sys.argv) > 1 else "screen.json"
    movie_genres = {g["id"]: short_genre(g["name"]) for g in get("/genre/movie/list")["genres"]}
    tv_genres = {g["id"]: short_genre(g["name"]) for g in get("/genre/tv/list")["genres"]}
    today = datetime.date.today()

    playing = get("/movie/now_playing", region=REGION)["results"]
    playing.sort(key=lambda item: -(item.get("popularity") or 0))
    theaters = [movie(item, movie_genres) for item in playing[:COUNT]]

    # (new to stream: out on a service in the region in the last six weeks, the most watched first)
    streaming_found = get("/discover/movie", region=REGION, watch_region=REGION, sort_by="popularity.desc",
                          with_release_type="4|6", with_watch_monetization_types="flatrate",
                          **{"release_date.gte": (today - datetime.timedelta(days=42)).isoformat(), "release_date.lte": today.isoformat()})["results"]
    streaming = [one for one in (movie(item, movie_genres) for item in streaming_found[:COUNT + 4]) if one.get("where")][:COUNT]

    trending = [item for item in get("/trending/tv/week")["results"] if set(item.get("origin_country") or []) & {"US", "GB", "CA", "AU"}]
    shows = [show(item, tv_genres) for item in trending[:COUNT]]

    data = {"made": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "region": REGION,
            "source": "TMDB (this product uses the TMDB API but is not endorsed or certified by TMDB)",
            "theaters": theaters, "streaming": streaming, "shows": shows}
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=True)
    with open(out_path, "w") as out:
        out.write(text)
    print(f"{out_path}: {len(theaters)} in theaters, {len(streaming)} new to stream, {len(shows)} shows ({len(text) // 1024} KB)")


if __name__ == "__main__":
    main()
