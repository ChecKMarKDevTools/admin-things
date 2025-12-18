import json
import subprocess
import sys
import os

def run_command(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running {' '.join(args)}: {result.stderr}", file=sys.stderr)
        return None
    return result.stdout

def get_repos(org):
    output = run_command(["gh", "repo", "list", org, "--limit", "1000", "--json", "nameWithOwner,isArchived"])
    if not output:
        return []
    repos = json.loads(output)
    return [r["nameWithOwner"] for r in repos if not r["isArchived"]]

def get_repo_labels(repo):
    output = run_command(["gh", "label", "list", "--repo", repo, "--json", "name,description,color"])
    if not output:
        return []
    return json.loads(output)

def sync_labels(repo, target_labels):
    existing_labels = {l["name"]: l for l in get_repo_labels(repo)}

    for target in target_labels:
        name = target["name"]
        color = target["color"]
        description = target["description"]

        if name in existing_labels:
            existing = existing_labels[name]
            if existing["color"].lower() != color.lower() or existing["description"] != description:
                print(f"Updating label '{name}' in {repo}")
                run_command(["gh", "label", "edit", name, "--repo", repo, "--color", color, "--description", description])
        else:
            print(f"Creating label '{name}' in {repo}")
            run_command(["gh", "label", "create", name, "--repo", repo, "--color", color, "--description", description])

def cleanup_labels(repo, target_label_names):
    existing_labels = get_repo_labels(repo)
    extra_labels = [l["name"] for l in existing_labels if l["name"] not in target_label_names]

    usage_report = []

    for label in extra_labels:
        # Check issues and PRs (gh issue list covers both if not specified, but let's be explicit)
        issues = json.loads(run_command(["gh", "issue", "list", "--repo", repo, "--label", label, "--json", "number,url,title"]) or "[]")
        prs = json.loads(run_command(["gh", "pr", "list", "--repo", repo, "--label", label, "--json", "number,url,title"]) or "[]")

        # Discussions might fail if not enabled
        discussions_output = run_command(["gh", "discussion", "list", "--repo", repo, "--label", label, "--json", "number,url,title"])
        discussions = json.loads(discussions_output) if discussions_output else []

        if not issues and not prs and not discussions:
            print(f"Deleting unused label '{label}' from {repo}")
            run_command(["gh", "label", "delete", label, "--repo", repo, "--yes"])
        else:
            for item in issues:
                usage_report.append({"label": label, "repo": repo, "type": "Issue", "number": item["number"], "url": item["url"], "title": item["title"]})
            for item in prs:
                usage_report.append({"label": label, "repo": repo, "type": "PR", "number": item["number"], "url": item["url"], "title": item["title"]})
            for item in discussions:
                usage_report.append({"label": label, "repo": repo, "type": "Discussion", "number": item["number"], "url": item["url"], "title": item["title"]})

    return usage_report

def main():
    org = "ChecKMarKDevTools"
    labels_file = ".github/org-labels.json"

    with open(labels_file, "r") as f:
        target_labels = json.load(f)

    target_label_names = [l["name"] for l in target_labels]
    repos = get_repos(org)

    all_usage = []

    for repo in repos:
        print(f"Processing {repo}...")
        sync_labels(repo, target_labels)
        usage = cleanup_labels(repo, target_label_names)
        all_usage.extend(usage)

    if all_usage:
        # Group by repo for the summary
        all_usage.sort(key=lambda x: (x["repo"], x["label"]))
        current_repo = ""
        for item in all_usage:
            if item["repo"] != current_repo:
                if current_repo:
                    print("::endgroup::")
                print(f"::group::Extra labels in {item['repo']}")
                current_repo = item["repo"]
            print(f"- Label '{item['label']}' is in use:")
            print(f"  - {item['type']} [#{item['number']}]({item['url']}): {item['title']}")
        if current_repo:
            print("::endgroup::")
    else:
        print("No extra labels in use.")

if __name__ == "__main__":
    main()
