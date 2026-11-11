#!/usr/bin/env python3
"""Live tests of bin/chainrun on the scheduler at hand (PBS or Slurm).

    python3 tests/live_chainrun.py [--queue Q] [--account A] [--dir DIR] [--only CASE]

Submits three short chains at once (time limit, finish, plain cancel) and checks the chain
states. Only a real scheduler shows that afterany holds the next attempt and how the time
limit signal arrives. Every job is deleted on exit, also on SIGTERM. About 10 minutes when
the queue is quiet.
"""
import argparse
import atexit
import importlib.machinery
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CHAINRUN = os.path.join(os.path.dirname(HERE), "bin", "chainrun")
loader = importlib.machinery.SourceFileLoader("chainrun", CHAINRUN)
chainrun = importlib.util.module_from_spec(importlib.util.spec_from_loader("chainrun", loader))
loader.exec_module(chainrun)

sched = chainrun.get_scheduler()
PBS = isinstance(sched, chainrun.Pbs)


def job_options(args, minutes, output=None):
    if PBS:
        options = ["-A", args.account, "-q", args.queue, "-l", "select=1:ncpus=1",
                   "-l", "walltime=00:%02d:00" % minutes, "-j", "oe"]
        return options + (["-o", output] if output else [])
    options = ["--time=00:%02d:00" % minutes] + (["--partition=" + args.queue] if args.queue else [])
    return options + (["--output=" + output] if output else [])


class Case:
    def __init__(self, name, body, minutes=2, output=None):
        self.name, self.body, self.minutes, self.output = name, body, minutes, output
        self.chain = None
        self.acted = False
        self.done_at = None
        self.errors = []

    def submit(self, args):
        script = os.path.join(args.dir, self.name + ".sh")
        with open(script, "w") as f:
            f.write("#!/bin/bash\n" + self.body)
        os.chmod(script, 0o755)
        options = job_options(args, self.minutes, self.output and os.path.join(args.dir, self.output))
        result = subprocess.run([sys.executable, CHAINRUN, "submit", "--max-attempts", "2",
                                 script, "--"] + options,
                                cwd=args.dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True)
        if result.returncode != 0:
            sys.exit("%s: submit failed: %s" % (self.name, result.stderr))
        self.chain = result.stdout.strip()
        print("%s: chain %s" % (self.name, self.chain))

    def history(self):
        return [" ".join(line.split()[1:]) for line in open(os.path.join(self.chain, "history"))]

    def has(self, prefix):
        return any(h.startswith(prefix) for h in self.history())

    def job(self, n):
        return [h.split()[2] for h in self.history() if h.startswith("submitted %d " % n)][0]

    def state(self):
        return chainrun.chain_state(chainrun.read_history(self.chain), sched.query, 2)

    def check(self, condition, what):
        if not condition:
            self.errors.append(what)

    def act(self):
        """Called every poll while the chain is live."""

    def verify(self):
        pass


class TimeLimit(Case):
    def __init__(self):
        Case.__init__(self, "time_limit", "sleep 300\n", output="time_limit.out")

    def verify(self):
        self.check(self.state() == "exhausted", "state %s" % self.state())
        self.check(self.has("started 2"), "attempt 2 did not start")
        if PBS:
            self.check(self.has("signaled 1"), "attempt 1 saw no SIGTERM")
        out = open(os.path.join(os.path.dirname(os.path.dirname(self.chain)), "time_limit.out")).read()
        self.check("=== chainrun attempt 1 of" in out and "=== chainrun attempt 2 of" in out,
                   "output file lacks both attempts' headers")


class Finish(Case):
    def __init__(self):
        Case.__init__(self, "finish", "sleep 5\nexit 0\n")

    def verify(self):
        self.check(self.state() == "done", "state %s" % self.state())
        self.check(not self.has("started 2"), "attempt 2 ran after the chain ended")
        self.check(sched.query(self.job(2)) in ("ended", "unknown"), "job 2 still live")


class Canceled(Case):
    """Delete the running attempt 1, expect attempt 2 to start, then stop the chain."""

    def __init__(self):
        Case.__init__(self, "cancel", "sleep 600\n", minutes=10)

    def act(self):
        if not self.acted and self.has("submitted 2"):
            time.sleep(10)
            print("%s: deleting job %s" % (self.name, self.job(1)))
            subprocess.run(["qdel" if PBS else "scancel", self.job(1)], check=True)
            self.acted = True
        elif self.acted and self.has("started 2"):
            subprocess.run([sys.executable, CHAINRUN, "stop", self.chain], check=True)

    def verify(self):
        self.check(self.state() == "stopped", "state %s" % self.state())
        self.check(self.has("started 2"), "attempt 2 did not start")
        if PBS:
            self.check(self.has("ended 1 exit=143 external"), "attempt 1 not recorded as external")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default="develop" if PBS else None)
    parser.add_argument("--account", default="UCIT0011")
    parser.add_argument("--dir", default=os.environ.get("SCRATCH") or os.getcwd())
    parser.add_argument("--only", help="run one case by name")
    args = parser.parse_args()
    args.dir = tempfile.mkdtemp(prefix="chainrun-live-", dir=args.dir)
    cases = [TimeLimit(), Finish(), Canceled()]
    if args.only:
        cases = [c for c in cases if c.name == args.only]

    def cleanup():
        for case in cases:
            if case.chain:
                subprocess.run([sys.executable, CHAINRUN, "stop", case.chain],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))

    for case in cases:
        case.submit(args)
    pending = list(cases)
    deadline = time.time() + 40 * 60
    while pending and time.time() < deadline:
        time.sleep(15)
        for case in list(pending):
            if case.state() == "live":
                case.act()
                continue
            if case.done_at is None:
                case.done_at = time.time()
            # Let the scheduler finish canceling and record the last job before checking
            if time.time() - case.done_at >= 90:
                case.verify()
                print("%s: %s" % (case.name, "ok" if not case.errors else "FAILED " + "; ".join(case.errors)))
                pending.remove(case)
    for case in pending:
        case.errors.append("still live after 40 minutes")
        print("%s: FAILED %s" % (case.name, case.errors))
    failed = [c for c in cases if c.errors]
    if not failed:
        shutil.rmtree(args.dir)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
