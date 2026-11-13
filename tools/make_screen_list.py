#!/usr/bin/env python3
"""The boards' Movies & TV list (2026-11-13; free sources that allow commercial use, 2026-11-13 evening): what's in
theaters, what's new to stream and this week's new shows and seasons, each with its genres, its age rating or rating,
and where to watch it.

    python3 tools/make_screen_list.py screen.json

Made once a day by the update site's nightly job (.github/workflows/screen.yml in tally-updates); every board reads the
small file it writes. No keys. The sources:
  - Wikidata (CC0): the films released in the US lately, their genres, age rating, distributor and critics' score.
  - Wikimedia's page views (CC0): how much each film or show is being looked up this week, for the order.
  - TVmaze (CC BY-SA, commercial use allowed with credit): the shows' premieres, networks, genres and ratings.
The list itself is CC BY-SA, as TVmaze's data is. Only the standard library, so the nightly job needs nothing installed.
"""
import datetime
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

AGENT = "TallyScoreboardList/1.0 (https://github.com/NicholasBohlen/tally-updates; tallboards@gmail.com)"  # (Wikimedia asks for a way to reach you)
COUNT = 10  # (each list: the board shows up to 8)
THEATER_DAYS = 35
STREAM_DAYS = 42

# Distributors that put films straight on their service: a film of theirs is "new to stream" there, not in theaters.
STREAMERS = {"Netflix": "Netflix", "Apple TV": "Apple TV", "Apple TV+": "Apple TV", "Apple Original Films": "Apple TV",
             "Amazon Prime Video": "Prime Video", "Prime Video": "Prime Video", "Hulu": "Hulu", "Disney+": "Disney+",
             "Max": "HBO Max", "HBO Max": "HBO Max", "Peacock": "Peacock", "Paramount+": "Paramount+", "Shudder": "Shudder",
             "Tubi": "Tubi", "Roku Channel": "Roku", "The Roku Channel": "Roku"}

# Wikidata's genres ("science fiction action film") as the panel's one or two words, the more telling first.
GENRES = [("documentary", "Documentary"), ("animat", "Animation"), ("horror", "Horror"), ("science fiction", "Sci-Fi"),
          ("superhero", "Superhero"), ("christmas", "Holiday"), ("musical", "Musical"), ("western", "Western"),
          ("thriller", "Thriller"), ("comedy", "Comedy"), ("romantic", "Romance"), ("romance", "Romance"),
          ("fantasy", "Fantasy"), ("action", "Action"), ("adventure", "Adventure"), ("heist", "Crime"), ("crime", "Crime"),
          ("mystery", "Mystery"), ("war", "War"), ("sport", "Sports"), ("biographical", "Biopic"), ("family", "Family"),
          ("children", "Family"), ("drama", "Drama")]


def fetch(url, accept="application/json", tries=5):
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": AGENT})
            with urllib.request.urlopen(request, timeout=60) as answer:
                return json.load(answer)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if attempt == tries - 1:
                raise
            wait = error.headers.get("Retry-After", "") if error.code == 429 else ""
            time.sleep(int(wait) if wait.isdigit() else 3 * (attempt + 1) * (3 if error.code == 429 else 1))
            continue
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
        time.sleep(2 + attempt * 3)


def plain(text):
    """The panel's letters: accents taken off ("Pokémon" -> "Pokemon"), curly quotes straightened, the rest kept."""
    text = (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-").replace("…", "...")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().strip()


def short_genres(labels):
    out = []
    joined = " | ".join(label.lower() for label in labels)
    for word, name in GENRES:
        if word in joined and name not in out:
            out.append(name)
    return out[:2]


def sparql(query):
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": query})
    return fetch(url, "application/sparql-results+json")["results"]["bindings"]


def week_views(articles):
    """Each English Wikipedia article's views over the last seven days (people, not bots)."""
    end = datetime.date.today() - datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=6)
    out = {}
    for article in articles:
        name = urllib.parse.quote(article.replace(" ", "_"), safe="")
        try:
            data = fetch("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
                         f"{name}/daily/{start:%Y%m%d}/{end:%Y%m%d}")
        except (urllib.error.URLError, TimeoutError):
            data = None  # (not counted: the rest of the list still made)
        out[article] = sum(item.get("views", 0) for item in (data or {}).get("items", []))
        time.sleep(0.2)
    return out


def article_of(url):
    return urllib.parse.unquote(url.rsplit("/wiki/", 1)[-1]).replace("_", " ") if url else ""


def title_of(label, article):
    """The film's name: its Wikidata label, or (no English label yet: "Q133341572") its article's, the "(2026 film)" off."""
    if label and not (label[0] == "Q" and label[1:].isdigit()):
        return plain(label)
    name = article
    if name.endswith(")") and " (" in name:
        name = name[:name.rfind(" (")]
    return plain(name)


def films(today):
    since = today - datetime.timedelta(days=max(THEATER_DAYS, STREAM_DAYS))
    rows = sparql(f"""
SELECT ?film ?filmLabel (MIN(?date) AS ?released) (SAMPLE(?certLabel) AS ?cert) (SAMPLE(?article) AS ?wiki)
       (GROUP_CONCAT(DISTINCT ?genreLabel; separator="|") AS ?genres) (GROUP_CONCAT(DISTINCT ?distLabel; separator="|") AS ?dists)
       (SAMPLE(?score) AS ?critics) WHERE {{
  ?film wdt:P31 wd:Q11424; p:P577 ?when. ?when ps:P577 ?date; pq:P291 wd:Q30.
  FILTER(?date >= "{since}T00:00:00Z"^^xsd:dateTime && ?date <= "{today}T23:59:59Z"^^xsd:dateTime)
  ?article schema:about ?film; schema:isPartOf <https://en.wikipedia.org/>.
  OPTIONAL {{ ?film wdt:P1657 ?certItem. ?certItem rdfs:label ?certLabel. FILTER(LANG(?certLabel) = "en") }}
  OPTIONAL {{ ?film wdt:P136 ?genre. ?genre rdfs:label ?genreLabel. FILTER(LANG(?genreLabel) = "en") }}
  OPTIONAL {{ ?film wdt:P750 ?dist. ?dist rdfs:label ?distLabel. FILTER(LANG(?distLabel) = "en") }}
  OPTIONAL {{ ?film p:P444 ?review. ?review ps:P444 ?score; pq:P447 wd:Q150248. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} GROUP BY ?film ?filmLabel""")
    found = []
    for row in rows:
        value = lambda key: (row.get(key) or {}).get("value", "")
        released = datetime.date.fromisoformat(value("released")[:10])
        article = article_of(value("wiki"))
        distributors = [name for name in value("dists").split("|") if name]
        where = next((STREAMERS[name] for name in distributors if name in STREAMERS), "")
        film = {"title": title_of(value("filmLabel"), article), "genres": short_genres(value("genres").split("|")),
                "released": released.isoformat(), "article": article}
        cert = value("cert").replace("Motion Picture Association film rating", "").strip()
        if cert in ("G", "PG", "PG-13", "R", "NC-17"):
            film["cert"] = cert
        score = value("critics").split("/")[0]
        if score.isdigit():
            film["critics"] = int(score)  # (Metacritic's, out of 100)
        if where:
            film["where"] = where
        if film["title"]:
            found.append(film)
    views = week_views({film["article"] for film in found})
    for film in found:
        film["views"] = views.get(film.pop("article"), 0)
    found.sort(key=lambda film: -film["views"])
    theaters = [film for film in found if not film.get("where") and film["released"] >= (today - datetime.timedelta(days=THEATER_DAYS)).isoformat()]
    streaming = [film for film in found if film.get("where")]
    for film in theaters + streaming:
        film.pop("released")
    return theaters[:COUNT], streaming[:COUNT]


def new_shows(today):
    """This week's series and season premieres (TVmaze: on the air and streaming, in the US or everywhere), most looked-up
    first (Wikipedia page views, through Wikidata's TVmaze IDs; TVmaze's own weight when a show has no article)."""
    shows = {}
    for days_back in range(7):
        day = (today - datetime.timedelta(days=days_back)).isoformat()
        for url in (f"https://api.tvmaze.com/schedule?country=US&date={day}", f"https://api.tvmaze.com/schedule/web?date={day}"):
            for episode in fetch(url) or []:
                show = episode.get("show") or (episode.get("_embedded") or {}).get("show") or {}
                if episode.get("number") != 1 or not show.get("id") or show.get("type") in ("News", "Talk Show", "Sports"):
                    continue
                channel = show.get("webChannel") or show.get("network") or {}
                country = (channel.get("country") or {}).get("code")
                if country not in (None, "US"):
                    continue
                shows.setdefault(show["id"], {"title": plain(show.get("name")), "genres": [{"Science-Fiction": "Sci-Fi"}.get(g, g) for g in (show.get("genres") or [])[:2]],
                                              "where": plain(channel.get("name")), "season": episode.get("season"),
                                              "rating": (show.get("rating") or {}).get("average"), "weight": show.get("weight") or 0})
        time.sleep(0.5)  # (TVmaze: 20 asks in 10 seconds)
    if not shows:
        return []
    ids = " ".join(f'"{show_id}"' for show_id in shows)
    rows = sparql(f"""
SELECT ?tvmaze ?article WHERE {{
  VALUES ?tvmaze {{ {ids} }}
  ?item wdt:P8600 ?tvmaze. ?article schema:about ?item; schema:isPartOf <https://en.wikipedia.org/>.
}}""")
    articles = {int(row["tvmaze"]["value"]): article_of(row["article"]["value"]) for row in rows}
    views = week_views(set(articles.values()))
    for show_id, show in shows.items():
        show["views"] = views.get(articles.get(show_id), 0) or show["weight"] * 10  # (no article: TVmaze's weight, low)
    ranked = sorted(shows.values(), key=lambda show: -show["views"])[:COUNT]
    for show in ranked:
        show.pop("weight")
        if show["rating"] is None:
            show.pop("rating")
        if show["season"] == 1:
            show["new"] = True
    return ranked


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "screen.json"
    today = datetime.date.today()
    theaters, streaming = films(today)
    shows = new_shows(today)
    data = {"made": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "region": "US",
            "license": "CC BY-SA 4.0", "sources": "Wikidata (CC0), Wikimedia page views (CC0), TVmaze (tvmaze.com, CC BY-SA)",
            "theaters": theaters, "streaming": streaming, "shows": shows}
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=True)
    with open(out_path, "w") as out:
        out.write(text)
    print(f"{out_path}: {len(theaters)} in theaters, {len(streaming)} new to stream, {len(shows)} new shows ({len(text) // 1024} KB)")


if __name__ == "__main__":
    main()
