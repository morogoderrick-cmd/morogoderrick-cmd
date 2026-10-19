"""Updates dark_mode.svg / light_mode.svg with live GitHub numbers.
Needs env vars:  ACCESS_TOKEN (classic PAT: repo + read:user)  and  USER_NAME."""
import os, json, datetime, hashlib
import requests
import xml.etree.ElementTree as ET
from dateutil import relativedelta

# ---------------------------------------------------------------- CONFIG
# "Uptime" counts from this date. >>> CHANGE THIS to your birth date (or any
# "since" date you prefer, e.g. when you started coding). <<<
UPTIME_SINCE = datetime.date(2004, 2, 28)
LINE_WIDTH   = 57            # must match W in tools/build_svg.py
SVG_FILES    = ["dark_mode.svg", "light_mode.svg"]
CACHE_FILE   = "cache/loc.json"
# ----------------------------------------------------------------------

TOKEN, USER = os.environ["ACCESS_TOKEN"], os.environ["USER_NAME"]
HEADERS = {"Authorization": f"bearer {TOKEN}"}
API = "https://api.github.com/graphql"


def gql(query, variables=None):
    r = requests.post(API, json={"query": query, "variables": variables or {}}, headers=HEADERS, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"GraphQL {r.status_code}: {r.text}")
    data = r.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def uptime_text():
    d = relativedelta.relativedelta(datetime.date.today(), UPTIME_SINCE)
    pl = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    return f"{pl(d.years,'year')}, {pl(d.months,'month')}, {pl(d.days,'day')}"


def user_info():
    q = """query($login:String!){ user(login:$login){ id createdAt
      followers{totalCount}
      repositories(ownerAffiliations:OWNER){totalCount}
      repositoriesContributedTo(contributionTypes:[COMMIT,ISSUE,PULL_REQUEST,REPOSITORY]){totalCount} } }"""
    u = gql(q, {"login": USER})["user"]
    return u["id"], u["createdAt"], u["followers"]["totalCount"], \
           u["repositories"]["totalCount"], u["repositoriesContributedTo"]["totalCount"]


def stars():
    total, cursor = 0, None
    q = """query($login:String!,$cursor:String){ user(login:$login){
      repositories(first:100, after:$cursor, ownerAffiliations:OWNER){
        nodes{stargazerCount} pageInfo{hasNextPage endCursor} } } }"""
    while True:
        r = gql(q, {"login": USER, "cursor": cursor})["user"]["repositories"]
        total += sum(n["stargazerCount"] for n in r["nodes"])
        if not r["pageInfo"]["hasNextPage"]:
            return total
        cursor = r["pageInfo"]["endCursor"]


def commits(created_at):
    q = """query($login:String!,$from:DateTime!,$to:DateTime!){ user(login:$login){
      contributionsCollection(from:$from,to:$to){ totalCommitContributions restrictedContributionsCount } } }"""
    start = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = datetime.datetime.now(datetime.timezone.utc)
    total = 0
    while start < now:
        end = min(start + datetime.timedelta(days=365), now)
        c = gql(q, {"login": USER, "from": start.isoformat(), "to": end.isoformat()})["user"]["contributionsCollection"]
        total += c["totalCommitContributions"] + c["restrictedContributionsCount"]
        start = end
    return total


def loc(user_id):
    cache = json.load(open(CACHE_FILE)) if os.path.exists(CACHE_FILE) else {}
    list_q = """query($cursor:String,$id:ID!){ viewer{ repositories(first:60, after:$cursor,
        ownerAffiliations:[OWNER,COLLABORATOR,ORGANIZATION_MEMBER]){
      nodes{ nameWithOwner defaultBranchRef{ target{ ... on Commit{ history(author:{id:$id}){totalCount} } } } }
      pageInfo{hasNextPage endCursor} } } }"""
    hist_q = """query($owner:String!,$name:String!,$id:ID!,$cursor:String){ repository(owner:$owner,name:$name){
      defaultBranchRef{ target{ ... on Commit{ history(first:100, after:$cursor, author:{id:$id}){
        nodes{additions deletions} pageInfo{hasNextPage endCursor} } } } } } }"""
    repos, cursor = [], None
    while True:
        r = gql(list_q, {"cursor": cursor, "id": user_id})["viewer"]["repositories"]
        repos += r["nodes"]
        if not r["pageInfo"]["hasNextPage"]:
            break
        cursor = r["pageInfo"]["endCursor"]

    add = dele = 0
    for repo in repos:
        name = repo["nameWithOwner"]
        ref = repo["defaultBranchRef"]
        if not ref or not ref["target"]:
            continue
        count = ref["target"]["history"]["totalCount"]
        c = cache.get(name)
        if c and c["commits"] == count:
            add += c["add"]; dele += c["del"]; continue
        a = d = 0; cur = None; owner, rname = name.split("/")
        while count:
            h = gql(hist_q, {"owner": owner, "name": rname, "id": user_id, "cursor": cur})
            hist = h["repository"]["defaultBranchRef"]["target"]["history"]
            for n in hist["nodes"]:
                a += n["additions"]; d += n["deletions"]
            if not hist["pageInfo"]["hasNextPage"]:
                break
            cur = hist["pageInfo"]["endCursor"]
        cache[name] = {"commits": count, "add": a, "del": d}
        add += a; dele += d
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    json.dump(cache, open(CACHE_FILE, "w"), indent=1)
    return add, dele


# ------------------------------------------------------------- SVG helpers
ET.register_namespace("", "http://www.w3.org/2000/svg")


def by_id(root, id_):
    for el in root.iter():
        if el.get("id") == id_:
            return el
    return None


def set_text(root, id_, text):
    el = by_id(root, id_)
    if el is not None:
        el.text = text


def fit(root, line_id, flex_dots_id):
    """Resize the dotted leader so the whole line is exactly LINE_WIDTH characters."""
    line, flex = by_id(root, line_id), by_id(root, flex_dots_id)
    if line is None or flex is None:
        return
    total = len("".join(line.itertext()))
    n = LINE_WIDTH - (total - len(flex.text))
    flex.text = " " + "." * max(n - 2, 1) + " "


def fixed(root, dots_id, value_id, slot):
    d, v = by_id(root, dots_id), by_id(root, value_id)
    if d is not None and v is not None:
        d.text = " " + "." * max(slot - len(v.text) - 2, 1) + " "


def fmt(n):
    return f"{n:,}"


def update(path, s):
    tree = ET.parse(path)
    root = tree.getroot()
    set_text(root, "age_data", s["age"]);         fit(root, "line_age", "age_data_dots")
    set_text(root, "repo_data", fmt(s["repos"])); fixed(root, "repo_data_dots", "repo_data", 8)
    set_text(root, "contrib_data", fmt(s["contrib"]))
    set_text(root, "star_data", fmt(s["stars"])); fit(root, "line_repo", "star_data_dots")
    set_text(root, "commit_data", fmt(s["commits"])); fixed(root, "commit_data_dots", "commit_data", 24)
    set_text(root, "follower_data", fmt(s["followers"])); fit(root, "line_commit", "follower_data_dots")
    set_text(root, "loc_data", fmt(s["add"] - s["del"]))
    set_text(root, "loc_add", fmt(s["add"])); set_text(root, "loc_del", fmt(s["del"]))
    fit(root, "line_loc", "loc_data_dots")
    tree.write(path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    uid, created, followers, repos, contrib = user_info()
    add, dele = loc(uid)
    stats = dict(age=uptime_text(), repos=repos, contrib=contrib, stars=stars(),
                 commits=commits(created), followers=followers, add=add, **{"del": dele})
    for f in SVG_FILES:
        update(f, stats)
    print("Updated:", stats)
