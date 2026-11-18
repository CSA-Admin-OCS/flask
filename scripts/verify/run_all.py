#!/usr/bin/env python
"""Run every check in scripts/verify/ and say which pass.

Each check is its own script that exits 0 when it passes. This runs them one after the other, each in its own
process (so they cannot disturb each other), and prints one line each: pass or FAIL, the seconds it took, the name.
The last lines of a failing check are shown under it. The exit code is 0 only if every check passed.

Usage:  python scripts/verify/run_all.py                    (from the flask repo root; five to six minutes in all)
        python scripts/verify/run_all.py permissions cors   (only the checks whose name contains one of these words)
        python scripts/verify/run_all.py --list             (the names, without running anything)
"""
import glob, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SHOWN = 8  # lines of a failing check's output to show
TIMEOUT = 900


def checks(words):
    names = sorted(glob.glob(os.path.join(HERE, "verify_*.py")))
    return [n for n in names if not words or any(w in os.path.basename(n) for w in words)]


def run(path):
    started = time.time()
    try:
        done = subprocess.run([sys.executable, path], cwd=REPO, capture_output=True, text=True, timeout=TIMEOUT)
        code, output = done.returncode, (done.stdout + done.stderr)
    except subprocess.TimeoutExpired:
        code, output = 1, "timed out after %d seconds" % TIMEOUT
    return code, time.time() - started, output


def main(argv):
    words = [a for a in argv if not a.startswith("--")]
    found = checks(words)
    if "--list" in argv:
        print("\n".join(os.path.basename(n) for n in found))
        return 0
    if not found:
        print("No check in scripts/verify/ matches: %s" % " ".join(words))
        return 1
    failed = []
    for path in found:
        code, seconds, output = run(path)
        name = os.path.basename(path)
        print("%-4s %5.0fs  %s" % ("pass" if code == 0 else "FAIL", seconds, name), flush=True)
        if code != 0:
            failed.append(name)
            print("\n".join("       " + line for line in output.strip().splitlines()[-SHOWN:]), flush=True)
    print("\n%d of %d checks pass." % (len(found) - len(failed), len(found)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
