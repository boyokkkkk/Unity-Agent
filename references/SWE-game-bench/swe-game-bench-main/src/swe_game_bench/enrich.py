"""Generate benchmark/issues/<instance_id>.txt from the real GitHub *issue* (title + body only).

For each instance this:
  1. Uses the instance's ``issue_url``. IMPORTANT: instance numbers are often
     *pull request* numbers, so the URL is never derived from the number --
     fetching the PR would leak the fix (PR title/body describe the solution).
  2. Fetches ONLY the issue title + body via the GitHub API. No comments.
  3. Replaces ``![alt](url)`` image refs in the body with a short factual
     description from a vision model.
  4. Writes "<title>\\n\\n<body-with-images-described>" and nothing else:
     no PR body, no fix SHA, no target file, no hints. Agents must solve from
     the issue title + body alone.

Env:
  GITHUB_TOKEN          recommended (avoids the 60 req/hr unauthenticated limit)
  OPENAI_API_KEY        required for image descriptions
  ENRICH_VISION_MODEL   override the vision model (default: gpt-5.2)
"""

from __future__ import annotations

import base64
import os
import re
import time

import requests

from . import paths
from .dataset import Instance, load_instances

VISION_MODEL = os.getenv("ENRICH_VISION_MODEL", "gpt-5.2")
IMG_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
ISSUE_URL_PATTERN = re.compile(r"github\.com/([^/]+)/([^/]+)/issues/(\d+)", re.IGNORECASE)
PULL_URL_PATTERN = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", re.IGNORECASE)

STALE_MARKERS = (
    "PR body",
    "Fix SHA",
    "Fix_Commit",
    "Target file:",
    "Expected code behavior",
    "Fixed by PR",
    "Original GitHub issue (auto-fetched)",
    "/pull/",
)

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI()
    return _client


def _github_headers() -> dict:
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.getenv("GITHUB_TOKEN", "").strip().strip("'\"")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def resolve_issue_url(instance: Instance) -> str | None:
    url = (instance.issue_url or "").strip().rstrip("/")
    if not url:
        return None
    if PULL_URL_PATTERN.search(url) and not ISSUE_URL_PATTERN.search(url):
        return None  # points at a PR -> would leak the fix
    if not ISSUE_URL_PATTERN.search(url):
        return None
    return url


def fetch_issue(issue_url: str) -> dict | None:
    m = ISSUE_URL_PATTERN.search(issue_url)
    if not m:
        print(f"  ! not an /issues/ URL: {issue_url}")
        return None
    org, repo, num = m.groups()
    api_url = f"https://api.github.com/repos/{org}/{repo}/issues/{num}"
    try:
        r = requests.get(api_url, headers=_github_headers(), timeout=30)
    except Exception as e:
        print(f"  ! GitHub API request failed: {e}")
        return None
    if r.status_code == 403 and "rate limit" in r.text.lower():
        print("  ! GitHub rate limit hit; set GITHUB_TOKEN")
        return None
    if r.status_code != 200:
        print(f"  ! GitHub API returned {r.status_code} for {api_url}")
        return None
    data = r.json()
    if "pull_request" in data:
        print(f"  ! {issue_url} resolves to a PULL REQUEST, not an issue; skipping")
        return None
    return data


def describe_image(image_url: str, alt: str) -> str | None:
    try:
        img_resp = requests.get(image_url, timeout=60)
        img_resp.raise_for_status()
        b64 = base64.b64encode(img_resp.content).decode()
        lower = image_url.lower().split("?", 1)[0]
        if lower.endswith(".png"):
            mime = "image/png"
        elif lower.endswith((".jpg", ".jpeg")):
            mime = "image/jpeg"
        elif lower.endswith(".gif"):
            mime = "image/gif"
        elif lower.endswith(".webp"):
            mime = "image/webp"
        else:
            mime = "image/png"
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text":
                    "You are describing a screenshot/image from a software bug report. "
                    "Write 2-4 sentences focusing on what a programmer would need to "
                    "understand the bug: UI element states, error messages, exact values, "
                    "layouts, visible code, stack traces, or anything text-readable. "
                    "Be factual and specific. Do NOT speculate about the fix. "
                    f"Image alt text from the issue: {alt or '(none)'}"},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }]
        resp = _get_client().chat.completions.create(model=VISION_MODEL, messages=messages)
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"    ! image description failed: {type(e).__name__}: {e}")
        return None


def enrich_image_refs(text: str, failures: list) -> str:
    def repl(m: re.Match) -> str:
        alt = m.group(1)
        url = m.group(2)
        print(f"  - describing image: {url[:80]}{'...' if len(url) > 80 else ''}")
        desc = describe_image(url, alt)
        label = f"[Image ({alt})" if alt else "[Image"
        if desc:
            return f"{label}: {desc}]"
        failures.append(url)
        return f"{label}: description unavailable]"
    return IMG_PATTERN.sub(repl, text)


def build_document(title: str, body: str, failures: list) -> str:
    title = (title or "").strip()
    body = (body or "").strip()
    if "![" in body:
        body = enrich_image_refs(body, failures)
    if not body:
        body = "(The GitHub issue has no body text.)"
    head = title if title else "(untitled issue)"
    return f"{head}\n\n{body}\n"


def is_stale(text: str) -> bool:
    low = text.lower()
    return any(marker.lower() in low for marker in STALE_MARKERS)


def enrich(instance_ids: list[str] | None = None, force: bool = False) -> int:
    issue_dir = paths.issues_dir()
    issue_dir.mkdir(parents=True, exist_ok=True)
    wanted = set(instance_ids or [])

    written = skipped = failed = 0
    img_failed: list[str] = []
    for instance in load_instances():
        iid = instance.instance_id
        if wanted and iid not in wanted:
            continue
        txt_path = issue_dir / f"{iid}.txt"

        if not (force or wanted):
            if txt_path.exists() and not is_stale(txt_path.read_text(encoding="utf-8", errors="replace")):
                print(f"[{iid}] up to date, skipping")
                skipped += 1
                continue

        issue_url = resolve_issue_url(instance)
        if not issue_url:
            print(f"[{iid}] no usable issue_url (points at a PR or missing) -- skipping")
            failed += 1
            continue

        print(f"[{iid}] fetching issue {issue_url}")
        issue = fetch_issue(issue_url)
        if issue is None:
            failed += 1
            continue

        failures: list = []
        doc = build_document(issue.get("title"), issue.get("body"), failures)
        txt_path.write_text(doc, encoding="utf-8")
        note = f"  ({len(failures)} image(s) NOT described)" if failures else ""
        print(f"  + wrote {txt_path}  (title + body only){note}")
        if failures:
            img_failed.append(iid)
        written += 1
        time.sleep(0.3)

    print(f"\n[summary] written={written}  skipped={skipped}  failed={failed}")
    if img_failed:
        print(f"[warn] image descriptions unavailable for: {' '.join(img_failed)}")
        print("       fix OPENAI_API_KEY quota/billing (or set ENRICH_VISION_MODEL) and re-run:")
        print(f"       swe-game-bench enrich {' '.join(img_failed)}")
    return 0 if failed == 0 else 1
