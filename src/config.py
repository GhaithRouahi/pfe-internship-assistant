import os
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_env = ROOT / ".env"   # KEY=value lines; real environment variables win
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            if v.strip() and not v.strip().startswith("PASTE_"):
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def load(name):
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


CFG = load("config.yaml")
# The three personal files can be swapped (tests use the *.example.yaml templates): PROFILE_FILE / PROJECTS_FILE / RESUMES_FILE
PROFILE = load(os.environ.get("PROFILE_FILE", "profile.yaml"))
PROJECTS = load(os.environ.get("PROJECTS_FILE", "projects.yaml"))
RESUMES = load(os.environ.get("RESUMES_FILE", "resumes.yaml"))["resumes"]
