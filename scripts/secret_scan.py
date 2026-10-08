"""Check candidate text for configured credentials without printing their values.

Scans tracked source and new project text; never reads or prints the .env file itself.
Configuration loads it normally. Binary artifacts and dependency directories are skipped.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chat"))
import config


def main():
    raw = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT)
    paths = sorted(set(raw.decode("utf-8").split("\0")) - {""})
    secrets = {"configured_neo4j_password": config.NEO4J_PASSWORD,
               "configured_llm_key": config.LLM_API_KEY}
    hits = []
    checked = 0
    patterns = (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
                re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{30,}"),
                re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"))
    for name in paths:
        path = ROOT / name
        if any(p in ("node_modules", ".git", ".venv", ".playwright-mcp") for p in path.parts):
            continue
        if path.name == ".env" or not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        checked += 1
        for label, value in secrets.items():
            if value and len(value) >= 8 and value in content:
                hits.append({"path": name, "kind": label})
        if any(pattern.search(content) for pattern in patterns):
            hits.append({"path": name, "kind": "credential_pattern"})
    for hit in hits:
        print(f"FAIL {hit['path']} ({hit['kind']}; value suppressed)")
    env_tracked = subprocess.check_output(["git", "ls-files", "--", ".env"], cwd=ROOT).strip()
    if env_tracked:
        print("FAIL .env is tracked")
    print(f"{'FAIL' if hits or env_tracked else 'PASS'}: checked {checked} text files; credential values never emitted")
    return 1 if hits or env_tracked else 0


if __name__ == "__main__":
    sys.exit(main())
