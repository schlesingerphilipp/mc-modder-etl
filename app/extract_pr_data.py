import requests
from typing import List, Dict, Any

REPOS = [
    "TheGreyGhost/MinecraftByExample",
    "TartaricAcid/TLMAdditionExample",
    "TartaricAcid/TouhouLittleMaid",
]

def get_pr_messages(repo: str) -> List[Dict[str, Any]]:
    url = f"https://api.github.com/repos/{repo}/pulls?state=all"
    pr_data = []
    response = requests.get(url)
    if response.status_code == 200:
        for pr in response.json():
            pr_data.append({
                "id": pr["id"],
                "title": pr["title"],
                "body": pr["body"],
                "user": pr["user"]["login"],
                "created_at": pr["created_at"],
                "merged_at": pr["merged_at"],
            })
    return pr_data

def extract_all_prs() -> Dict[str, List[Dict[str, Any]]]:
    results = {}
    for repo in REPOS:
        results[repo] = get_pr_messages(repo)
    return results

if __name__ == "__main__":
    all_prs = extract_all_prs()
    print(f"Extracted PRs for {len(all_prs)} repositories.")
