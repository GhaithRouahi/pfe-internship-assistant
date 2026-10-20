"""Runs every offline test against the fictional *.example.yaml files (no personal data, no browser login needed).
Usage: python tests/run_all.py"""
import os, subprocess, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
env = dict(os.environ, PROFILE_FILE="profile.example.yaml", PROJECTS_FILE="projects.example.yaml", RESUMES_FILE="tests/fixtures/resumes.yaml", PYTHONUTF8="1")
failed = 0
for t in ("test_answers.py", "test_answers2.py", "test_safety.py", "test_pipeline.py", "test_forms.py"):
    print("==", t, flush=True)
    r = subprocess.run([sys.executable, "-W", "ignore", f"tests/{t}"], cwd=ROOT, env=env)
    failed += r.returncode != 0
sys.exit(1 if failed else 0)
