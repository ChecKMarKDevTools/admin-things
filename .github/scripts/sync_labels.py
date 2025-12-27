import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"


def token() -> str:
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not t:
        print("Missing GH_TOKEN (or GITHUB_TOKEN).", file=sys.stderr)
        sys.exit(2)
    return t


def api(method: str, url: str, t: str, *, params=None, body=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {t}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "admin-things",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return None if not raw else json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        print(f"GitHub API error {e.code} {method} {url}: {raw[:2000]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"GitHub API failed {method} {url}: {e}", file=sys.stderr)
        return None


def paged(path: str, t: str, *, params=None):
    out: list[dict] = []
    page = 1
    while True:
        p = dict(params or {})
        p["per_page"] = 100
        p["page"] = page
        batch = api("GET", f"{API}{path}", t, params=p)
        if batch is None:
            return None
        if not batch:
            return out
        if not isinstance(batch, list):
            print(f"Expected list from {path}", file=sys.stderr)
            return None
        out.extend(batch)
        page += 1


def has_issues_or_prs(repo: str, label: str, t: str) -> bool | None:
    data = api(
        "GET",
        f"{API}/repos/{repo}/issues",
        t,
        params={"state": "all", "labels": label, "per_page": 1},
    )
    if data is None:
        return None
    if not isinstance(data, list):
        return None
    return len(data) > 0


def has_discussions(repo: str, label: str, t: str) -> bool | None:
    q = f'repo:{repo} label:"{label}"'
    query = """query($q: String!) {
  search(query: $q, type: DISCUSSION, first: 1) { discussionCount }
}
"""
    data = api(
        "POST",
        GRAPHQL,
        t,
        body={"query": query, "variables": {"q": q}},
    )
    if data is None or data.get("errors"):
        return None
    try:
        return int(data["data"]["search"]["discussionCount"]) > 0
    except Exception:
        return None


def list_repos(org: str, t: str):
    repos = paged(f"/orgs/{org}/repos", t, params={"type": "all"})
    if repos is None:
        return []
    return [r["full_name"] for r in repos if not r.get("archived")]


def list_labels(repo: str, t: str):
    labels = paged(f"/repos/{repo}/labels", t)
    if labels is None:
        return []
    out = []
    for l in labels:
        name = l.get("name")
        color = l.get("color")
        if not name or not color:
            continue
        out.append({"name": name, "color": color, "description": l.get("description") or ""})
    return out


def label_create(repo: str, name: str, color: str, description: str, t: str):
    api(
        "POST",
        f"{API}/repos/{repo}/labels",
        t,
        body={"name": name, "color": color, "description": description},
    )


def label_update(repo: str, name: str, color: str, description: str, t: str):
    enc = urllib.parse.quote(name, safe="")
    api(
        "PATCH",
        f"{API}/repos/{repo}/labels/{enc}",
        t,
        body={"color": color, "description": description},
    )


def label_delete(repo: str, name: str, t: str):
    enc = urllib.parse.quote(name, safe="")
    api("DELETE", f"{API}/repos/{repo}/labels/{enc}", t)

def sync_labels(repo, target_labels):
    t = token()
    existing_labels = {l["name"]: l for l in list_labels(repo, t)}

    for target in target_labels:
        name = target["name"]
        color = target["color"]
        description = target["description"]

        if name in existing_labels:
            existing = existing_labels[name]
            if existing["color"].lower() != color.lower() or existing["description"] != description:
                print(f"Updating label '{name}' in {repo}")
                label_update(repo, name, color, description, t)
        else:
            print(f"Creating label '{name}' in {repo}")
            label_create(repo, name, color, description, t)

def cleanup_labels(repo, target_label_names):
    t = token()
    existing_labels = list_labels(repo, t)
    extra_labels = [l["name"] for l in existing_labels if l["name"] not in target_label_names]

    for label in extra_labels:
        used_in_issues_or_prs = has_issues_or_prs(repo, label, t)
        used_in_discussions = has_discussions(repo, label, t)

        # Fail safe: if any usage-check failed, do not delete.
        checks_failed = used_in_issues_or_prs is None or used_in_discussions is None
        if checks_failed:
            print(
                f"Skipping deletion check for label '{label}' in {repo}: "
                "one or more usage checks failed",
                file=sys.stderr,
            )
            continue

        if not used_in_issues_or_prs and not used_in_discussions:
            print(f"Deleting unused label '{label}' from {repo}")
            label_delete(repo, label, t)
        else:
            print(f"Keeping label '{label}' in {repo}: in use")

def main():
    org = "ChecKMarKDevTools"
    labels_file = ".github/org-labels.json"

    t = token()

    with open(labels_file, "r") as f:
        target_labels = json.load(f)

    target_label_names = [l["name"] for l in target_labels]
    repos = list_repos(org, t)

    for repo in repos:
        print(f"Processing {repo}...")
        sync_labels(repo, target_labels)
        cleanup_labels(repo, target_label_names)

    print("Done.")

if __name__ == "__main__":
    main()
