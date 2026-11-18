"""Tests for bin/chainrun.

Run with: python3 -m unittest tests/test_chainrun.py

StateTest reads histories and scheduler output with no processes. CommandTest runs single
chainrun commands against the recording fake in fake_scheduler.py and moves the fake's jobs
between states itself. The live scheduler is covered by live_chainrun.py.
"""
import importlib.machinery
import importlib.util
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHAINRUN = os.path.join(os.path.dirname(HERE), "bin", "chainrun")
sys.path.insert(0, HERE)
import fake_scheduler  # noqa: E402

loader = importlib.machinery.SourceFileLoader("chainrun", CHAINRUN)
chainrun = importlib.util.module_from_spec(importlib.util.spec_from_loader("chainrun", loader))
loader.exec_module(chainrun)


def printed(result):
    """The labeled lines a command printed, as a dict."""
    return dict(line.split(None, 1) for line in result.stdout.splitlines())


def history(*lines):
    return [("2026-11-11T12:00:00 " + line).split() for line in lines]


class StateTest(unittest.TestCase):
    def state(self, job_states, *lines, max_attempts=2):
        return chainrun.chain_state(history(*lines), lambda job: job_states.get(job, "unknown"),
                                    max_attempts)

    def test_final_line_decides(self):
        self.assertEqual(self.state({}, "submitted 1 a", "chain done exit=0"), "done")
        self.assertEqual(self.state({}, "submitted 1 a", "chain failed exit=3"), "failed")
        self.assertEqual(self.state({"a": "running"}, "submitted 1 a", "chain stopped"), "stopped")

    def test_live_while_a_job_is_queued_or_running(self):
        self.assertEqual(self.state({"a": "running"}, "submitted 1 a"), "live")
        self.assertEqual(self.state({"a": "ended", "b": "queued"}, "submitted 1 a",
                                    "started 1 a host", "submitted 2 b"), "live")

    def test_out_of_attempts_after_the_last_attempt(self):
        self.assertEqual(self.state({}, "submitted 1 a", "started 1 a host", "submitted 2 b",
                                    "started 2 b host"), "out-of-attempts")

    def test_lost_when_nothing_is_queued(self):
        self.assertEqual(self.state({}, "submitted 1 a", "started 1 a host"), "lost")
        self.assertEqual(self.state({}, "submitted 1 a", "submitted 2 b"), "lost")

    def test_unknown_when_a_query_failed(self):
        self.assertEqual(self.state({"a": "error"}, "submitted 1 a"), "unknown")
        self.assertEqual(self.state({"a": "error", "b": "queued"}, "submitted 1 a",
                                    "submitted 2 b"), "live")

    def test_job_known_only_from_its_started_line(self):
        lines = ("submitted 1 a", "started 1 a host", "started 2 b host")
        self.assertEqual(self.state({"b": "running"}, *lines), "live")
        self.assertEqual(self.state({}, *lines), "out-of-attempts")
        self.assertEqual(chainrun.chain_jobs(history(*lines)), ["a", "b"])

    def pbs(self, job_state):
        """State from `qstat -xf` output for a job in job_state, with one wrapped line."""
        return chainrun.Pbs.parse("Job Id: 8052953.desched1\n"
                                  "    Job_Name = run.sh\n"
                                  "    job_state = %s\n"
                                  "    Variable_List = PBS_O_HOME=/home/user,PBS_O_LANG=en_US.UTF-8,\n"
                                  "\tPBS_O_WORKDIR=/home/user/run\n"
                                  "    Exit_status = 3\n" % job_state)

    def test_pbs_output(self):
        self.assertEqual(self.pbs("R"), "running")
        self.assertEqual(self.pbs("E"), "running")
        self.assertEqual(self.pbs("Q"), "queued")
        self.assertEqual(self.pbs("H"), "queued")
        self.assertEqual(self.pbs("F"), "ended")
        self.assertEqual(chainrun.Pbs.parse(""), "unknown")

    def test_pbs_submit_arguments(self):
        text = ("Job Id: 8052953.desched1\n"
                "    Submit_arguments = -q main -o /home/user/logs -k doe -r n /home/user/a dir/.chainr\n"
                "\tun/run.sh.20261118/batch/2/run.sh\n"
                "    job_state = Q\n")
        self.assertEqual(chainrun.Pbs.attributes(text)["Submit_arguments"],
                         "-q main -o /home/user/logs -k doe -r n /home/user/a dir/.chainrun/run.sh.20261118/batch/2/run.sh")

    def test_slurm_output(self):
        parse = chainrun.Slurm.parse
        self.assertEqual(parse("RUNNING\n", ""), "running")
        self.assertEqual(parse("PENDING\n", ""), "queued")
        self.assertEqual(parse("COMPLETED\n", ""), "ended")
        self.assertEqual(parse("", "CANCELLED by 1000\n"), "ended")
        self.assertEqual(parse("", "RUNNING\n"), "running")
        self.assertEqual(parse("", ""), "unknown")
        self.assertEqual(parse("REQUEUE_HOLD\n", ""), "queued")
        self.assertEqual(parse("", "OUT_OF_MEMORY\n"), "ended")

    def test_leading_block(self):
        tmp = tempfile.mkdtemp(prefix="chainrun-test-")
        self.addCleanup(shutil.rmtree, tmp)
        script = os.path.join(tmp, "run.sh")
        with open(script, "w") as f:
            f.write("#!/bin/bash\n#PBS -N x\n# a comment\n\necho hi\n#PBS -N late\n")
        self.assertEqual(chainrun.leading_block(script), ["#PBS -N x\n", "# a comment\n", "\n"])


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="chainrun-test-"))
        self.fake = fake_scheduler.Fake(os.path.join(self.tmp, "fake"))
        self.env = dict(os.environ, CHAINRUN_SCHEDULER="fake:" + self.fake.dir, PYTHONPATH=HERE,
                        CHAINRUN_SUBMIT_DELAY="0")
        self.addCleanup(shutil.rmtree, self.tmp)

    def chainrun(self, *args, check=True, job_id=None, cwd=None, env=None):
        env = dict(env or self.env)
        if job_id:
            env["CHAINRUN_FAKE_JOB_ID"] = str(job_id)
        result = subprocess.run([sys.executable, CHAINRUN] + list(args), env=env,
                                cwd=cwd or self.tmp, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def script(self, body, name="run.sh", shebang="#!/bin/bash\n"):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(shebang + body)
        os.chmod(path, 0o755)
        return path

    def submit(self, body, max_attempts=2, options=(), **kwargs):
        result = self.chainrun("submit", "--max-attempts", str(max_attempts),
                               self.script(body, **kwargs), "--", *options)
        return printed(result)["chain"]

    def attempt(self, chain, n, check=True, **kwargs):
        """Run attempt n as the fake's job n."""
        return self.chainrun("attempt", chain, str(n), check=check, job_id=n, **kwargs)

    def start_attempt(self, chain, n):
        """Attempt n in the background, in its own process group like a batch job."""
        env = dict(self.env, CHAINRUN_FAKE_JOB_ID=str(n))
        proc = subprocess.Popen([sys.executable, CHAINRUN, "attempt", chain, str(n)], env=env,
                                cwd=self.tmp, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(proc.wait)
        self.wait_for(os.path.join(self.tmp, "running"))
        return proc

    def wait_for(self, path, timeout=10):
        start = time.time()
        while not os.path.exists(path):
            self.assertLess(time.time() - start, timeout, "no %s after %ss" % (path, timeout))
            time.sleep(0.05)

    def status(self, chain):
        return self.chainrun("status", chain).stdout.split()[0]

    def history(self, chain):
        with open(os.path.join(chain, "history")) as f:
            return [" ".join(line.split()[1:]) for line in f]

    def assert_lines(self, chain, *expected):
        history = self.history(chain)
        for line in expected:
            self.assertTrue(any(h.startswith(line) for h in history), "%r not in %s" % (line, history))

    def assert_no_line(self, chain, prefix):
        history = self.history(chain)
        self.assertFalse(any(h.startswith(prefix) for h in history), "%r in %s" % (prefix, history))

    # ---- outcomes of one attempt

    def test_submit_prints_the_job_and_the_chain(self):
        script = self.script("exit 0\n")
        result = printed(self.chainrun("submit", script))
        self.assertEqual(result["job"], "1")
        self.assertTrue(os.path.isfile(os.path.join(result["chain"], "chain.json")))

    def test_finish(self):
        chain = self.submit("exit 0\n")
        self.assertEqual(self.attempt(chain, 1).returncode, 0)
        self.assert_lines(chain, "started 1 1", "submitted 2 2", "ended 1 exit=0 done",
                          "chain done exit=0")
        self.assertEqual(self.fake.log(), ["submit 1 after=None", "submit 2 after=1", "cancel 2"])
        self.assertEqual(self.status(chain), "done")

    def test_fail(self):
        chain = self.submit("exit 3\n")
        self.assertEqual(self.attempt(chain, 1, check=False).returncode, 3)
        self.assert_lines(chain, "ended 1 exit=3 failed", "chain failed exit=3")
        self.assertEqual(self.fake.log()[-1], "cancel 2")
        self.assertEqual(self.status(chain), "failed")

    def test_continue(self):
        chain = self.submit("[ -e once ] && exit 0\ntouch once\nexit 75\n")
        self.assertEqual(self.attempt(chain, 1, check=False).returncode, 75)
        self.assert_lines(chain, "ended 1 exit=75 continue")
        self.assertNotIn("cancel 2", self.fake.log())
        self.assertEqual(self.status(chain), "live")
        self.attempt(chain, 2)
        self.assert_lines(chain, "started 2 2", "ended 2 exit=0 done", "chain done exit=0")
        self.assertEqual(self.fake.log(), ["submit 1 after=None", "submit 2 after=1"])

    def test_crash(self):
        chain = self.submit("kill -SEGV $$\n")
        self.attempt(chain, 1, check=False)
        self.assert_lines(chain, "ended 1 exit=139 failed")

    def test_last_attempt_queues_nothing(self):
        chain = self.submit("exit 75\n", max_attempts=1)
        self.attempt(chain, 1, check=False)
        self.assertEqual(self.fake.log(), ["submit 1 after=None"])
        self.fake.set_job("1", state="ended")
        self.assertEqual(self.status(chain), "out-of-attempts")

    def test_sigterm_marks_the_attempt_external(self):
        chain = self.submit("touch running\nsleep 30\n")
        proc = self.start_attempt(chain, 1)
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait()
        self.assert_lines(chain, "signaled 1", "ended 1 exit=143 external")
        self.assert_no_line(chain, "chain")

    def test_sigterm_handler_that_exits_zero(self):
        chain = self.submit("trap 'exit 0' TERM\ntouch running\nsleep 30 & wait\n")
        proc = self.start_attempt(chain, 1)
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait()
        self.assert_lines(chain, "ended 1 exit=0 external")

    def test_sigterm_to_the_script_alone_is_external(self):
        chain = self.submit("echo $$ > pid\ntouch running\nexec sleep 30\n")
        proc = self.start_attempt(chain, 1)
        with open(os.path.join(self.tmp, "pid")) as f:
            os.kill(int(f.read()), signal.SIGTERM)
        self.assertEqual(proc.wait(), 143)
        self.assert_lines(chain, "ended 1 exit=143 external")
        self.assert_no_line(chain, "chain")
        self.assertNotIn("cancel 2", self.fake.log())

    def test_signals_to_the_wrapper_reach_the_script(self):
        for name in ("TERM", "USR1", "USR2"):
            with self.subTest(signal=name):
                os.makedirs(os.path.join(self.tmp, name))
                body = "trap 'kill $!; exit 75' %s\ntouch running\nsleep 30 & wait\n" % name
                chain = self.submit(body, name=name + "/run.sh")
                proc = self.start_attempt(chain, 1)
                os.remove(os.path.join(self.tmp, "running"))
                os.kill(proc.pid, getattr(signal, "SIG" + name))
                self.assertEqual(proc.wait(), 75)
                outcome = "external" if name == "TERM" else "continue"
                self.assert_lines(chain, "ended 1 exit=75 " + outcome)

    def test_sigterm_before_the_script_starts(self):
        chain = self.submit("touch ran\nexit 0\n")
        with open(os.path.join(self.fake.dir, "refuse"), "w") as f:
            f.write("the queue is full\n")
        env = dict(self.env, CHAINRUN_FAKE_JOB_ID="1", CHAINRUN_SUBMIT_DELAY="1")
        proc = subprocess.Popen([sys.executable, CHAINRUN, "attempt", chain, "1"], env=env,
                                cwd=self.tmp, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        self.addCleanup(proc.wait)
        start = time.time()
        while "started 1 1" not in " ".join(self.history(chain)):
            self.assertLess(time.time() - start, 10, "attempt 1 did not start")
            time.sleep(0.05)
        os.kill(proc.pid, signal.SIGTERM)
        self.assertEqual(proc.wait(), 143)
        self.assert_lines(chain, "signaled 1", "ended 1 exit=143 external")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "ran")))

    def test_attempt_after_the_chain_ended(self):
        open(os.path.join(self.fake.dir, "cancel_fails"), "w").close()
        chain = self.submit("echo ran >> runs\n")
        self.attempt(chain, 1)
        self.assert_lines(chain, "chain done exit=0", "error could not cancel attempt 2")
        self.attempt(chain, 2)
        self.assert_no_line(chain, "started 2")
        with open(os.path.join(self.tmp, "runs")) as f:
            self.assertEqual(f.read(), "ran\n")

    def test_next_submission_refused(self):
        chain = self.submit("touch ran\nexit 75\n")
        with open(os.path.join(self.fake.dir, "refuse"), "w") as f:
            f.write("the queue is full\nand the second line says more\n")
        self.attempt(chain, 1, check=False)
        self.assert_lines(chain, "error could not queue attempt 2: the queue is full and the",
                          "ended 1 exit=75 continue")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "ran")))
        self.fake.set_job("1", state="ended")
        self.assertEqual(self.status(chain), "lost")

    def test_next_submission_retried(self):
        chain = self.submit("exit 75\n")
        open(os.path.join(self.fake.dir, "refuse_once"), "w").close()
        self.attempt(chain, 1, check=False)
        self.assert_lines(chain, "submitted 2 2")
        self.assert_no_line(chain, "error")
        self.assertEqual(self.fake.log(), ["submit 1 after=None", "submit 2 after=1"])

    def test_next_submission_made_after_the_script(self):
        refuse = os.path.join(self.fake.dir, "refuse")
        chain = self.submit("rm %s\nexit 75\n" % shlex.quote(refuse))
        with open(refuse, "w") as f:
            f.write("the queue is full\n")
        self.attempt(chain, 1, check=False)
        self.assertEqual(self.history(chain)[-3:], ["error could not queue attempt 2: the queue is full",
                                                    "ended 1 exit=75 continue", "submitted 2 2"])
        self.assertEqual(self.status(chain), "live")

    def test_next_submission_made_after_a_signal(self):
        refuse = os.path.join(self.fake.dir, "refuse")
        chain = self.submit("rm %s\ntouch running\nsleep 30\n" % shlex.quote(refuse))
        with open(refuse, "w") as f:
            f.write("the queue is full\n")
        proc = self.start_attempt(chain, 1)
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait()
        self.assert_lines(chain, "ended 1 exit=143 external", "submitted 2 2")

    def test_wrapper_error(self):
        chain = self.submit("exit 0\n")
        os.chmod(os.path.join(chain, "script.sh"), 0o644)
        self.assertEqual(self.attempt(chain, 1, check=False).returncode, 1)
        self.assert_lines(chain, "ended 1 exit=1 failed", "chain failed exit=1")
        self.assertEqual(self.fake.log()[-1], "cancel 2")

    # ---- script, options and files

    def test_frozen_copy(self):
        chain = self.submit("echo original > out\n")
        self.script("echo changed > out\n")
        self.attempt(chain, 1)
        with open(os.path.join(self.tmp, "out")) as f:
            self.assertEqual(f.read().strip(), "original")

    def test_directives_and_options(self):
        body = '#PBS -N "a name"\n#PBS -l select=1:ncpus=1\n# a comment with $PWD and *\n\nexit 0\n#PBS -N late\n'
        chain = self.submit(body, options=["-N", "from cli", "--glob=*.txt"])
        with open(os.path.join(chain, "batch", "1", "run.sh")) as f:
            batch = f.read()
        self.assertIn('#PBS -N "a name"\n#PBS -l select=1:ncpus=1\n# a comment with $PWD and *\n\nexec ', batch)
        self.assertNotIn("late", batch)
        self.assertEqual(chainrun.read_config(chain)["options"], ["-N", "from cli", "--glob=*.txt"])
        self.assertEqual(os.stat(os.path.join(chain, "env.json")).st_mode & 0o777, 0o600)

    def test_saved_environment_removed(self):
        def saved(chain):
            return os.path.exists(os.path.join(chain, "env.json"))
        chain = self.submit("exit 75\n")
        self.attempt(chain, 1, check=False)
        self.assertTrue(saved(chain))
        self.attempt(chain, 2, check=False)
        self.assertFalse(saved(chain), "kept after the last attempt started")
        chain = self.submit("exit 0\n")
        self.attempt(chain, 1)
        self.assertFalse(saved(chain), "kept after the chain ended")
        chain = self.submit("exit 0\n")
        self.chainrun("stop", chain)
        self.assertFalse(saved(chain), "kept after stop")

    def test_script_without_shebang(self):
        chain = self.submit("exit 0\n", shebang="")
        self.attempt(chain, 1)
        self.assert_lines(chain, "chain done exit=0")

    def test_shebang_honored(self):
        chain = self.submit("raise SystemExit(0)\n", name="run.py", shebang="#!/usr/bin/env python3\n")
        self.attempt(chain, 1)
        self.assert_lines(chain, "chain done exit=0")

    def test_paths_with_spaces(self):
        chain = self.submit("exit 0\n", name="a dir/my script.sh")
        self.assertIn("a dir/.chainrun/my script.sh.", chain)
        self.attempt(chain, 1)
        self.assert_lines(chain, "chain done exit=0")

    def test_submit_cwd_and_environment(self):
        chain = self.submit("exit 75\n")
        self.attempt(chain, 1, check=False, cwd="/", env=dict(self.env, MARK="from attempt 1"))
        job = self.fake.jobs()["2"]
        self.assertEqual(job["cwd"], self.tmp)
        self.assertNotIn("MARK", job["env"])

    def test_secrets_left_out_of_the_environment(self):
        env = dict(self.env, GITHUB_TOKEN="t", AWS_SECRET_ACCESS_KEY="s", DB_PASSWORD="p",
                   MARK="kept")
        chain = printed(self.chainrun("submit", self.script("exit 0\n"), env=env))["chain"]
        saved = chainrun.read_env(chain)
        self.assertEqual(saved["MARK"], "kept")
        for name in ("GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "DB_PASSWORD"):
            self.assertNotIn(name, saved)
        self.assertNotIn("GITHUB_TOKEN", self.fake.jobs()["1"]["env"])

    def test_submit_failure(self):
        with open(os.path.join(self.fake.dir, "refuse"), "w") as f:
            f.write("no\n")
        result = self.chainrun("submit", self.script("exit 0\n"), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no", result.stderr)
        self.assertEqual(os.listdir(os.path.join(self.tmp, ".chainrun")), [".gitignore"])

    def test_two_submits_in_a_row(self):
        script = self.script("exit 0\n")
        first = printed(self.chainrun("submit", script))["chain"]
        second = printed(self.chainrun("submit", script))["chain"]
        self.assertNotEqual(first, second)

    def test_chains_hidden_from_git(self):
        self.submit("exit 0\n")
        with open(os.path.join(self.tmp, ".chainrun", ".gitignore")) as f:
            self.assertEqual(f.read(), "*\n")

    def test_submit_removes_old_chains(self):
        script = self.script("exit 0\n")
        old = printed(self.chainrun("submit", script))["chain"]
        recent = printed(self.chainrun("submit", script))["chain"]
        for chain, days in ((old, 31), (recent, 29)):
            changed = time.time() - days * 86400
            os.utime(os.path.join(chain, "history"), (changed, changed))
        self.chainrun("submit", script)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(recent))

    # ---- stop

    def test_stop_cancels_the_queued_then_the_running_job(self):
        chain = self.submit("exit 75\n")
        self.attempt(chain, 1, check=False)
        self.fake.set_job("1", state="running")
        self.chainrun("stop", chain)
        self.assert_lines(chain, "chain stopped")
        self.assertEqual(self.fake.log()[-2:], ["cancel 2", "cancel 1"])
        self.assertEqual(self.status(chain), "stopped")

    def test_stop_skips_ended_jobs(self):
        chain = self.submit("exit 75\n")
        self.attempt(chain, 1, check=False)
        self.fake.set_job("1", state="ended")
        self.chainrun("stop", chain)
        self.assertEqual(self.fake.log()[-1], "cancel 2")
        self.assertNotIn("cancel 1", self.fake.log())

    def test_stop_of_an_ended_chain(self):
        chain = self.submit("exit 0\n")
        self.attempt(chain, 1)
        self.fake.set_job("1", state="ended")
        result = self.chainrun("stop", chain, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already done", result.stderr)

    def test_stop_again_after_a_failed_cancel(self):
        chain = self.submit("exit 75\n")
        self.attempt(chain, 1, check=False)
        self.fake.set_job("1", state="running")
        cancel_fails = os.path.join(self.fake.dir, "cancel_fails")
        open(cancel_fails, "w").close()
        result = self.chainrun("stop", chain, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("2 of 2 jobs not canceled", result.stderr)
        os.remove(cancel_fails)
        self.chainrun("stop", chain)
        self.assertEqual(self.fake.log()[-2:], ["cancel 2", "cancel 1"])
        self.assertEqual(self.history(chain).count("chain stopped"), 1)

    def test_stop_cancels_jobs_whose_query_failed(self):
        chain = self.submit("exit 75\n")
        self.attempt(chain, 1, check=False)
        open(os.path.join(self.fake.dir, "query_fails"), "w").close()
        self.assertEqual(self.status(chain), "unknown")
        result = self.chainrun("stop", chain)
        self.assertIn("could not query job 2", result.stderr)
        self.assertEqual(self.fake.log()[-2:], ["cancel 2", "cancel 1"])
        self.assert_lines(chain, "chain stopped")

    def test_stop_and_status_by_job_id(self):
        chain = self.submit("exit 75\n", name="a dir/run.sh")
        self.attempt(chain, 1, check=False)
        self.fake.set_job("1", state="running")
        self.assertEqual(self.status("2"), "live")
        self.chainrun("stop", "2")
        self.assertEqual(self.fake.log()[-2:], ["cancel 2", "cancel 1"])
        self.assertEqual(self.status(chain), "stopped")

    def test_job_found_after_other_arguments(self):
        chain = self.submit("exit 0\n", name="a dir/run.sh")
        batch = os.path.join(chain, "batch", "1", "run.sh")
        self.fake.set_job("1", batch="-q main -o /tmp/out -k doe " + batch)
        self.assertEqual(chainrun.find_chain("1", self.fake), chain)

    def test_stop_of_a_job_not_in_a_chain(self):
        self.fake.set_job("7", batch="/home/user/plain.sh")
        for job in ("7", "8"):
            result = self.chainrun("stop", job, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("%s is not a chain directory or a job of a chain" % job, result.stderr)

    def test_stop_cancels_a_job_missing_from_the_submitted_lines(self):
        chain = self.submit("exit 75\n")
        self.attempt(chain, 1, check=False)
        with open(os.path.join(chain, "history")) as f:
            lines = [line for line in f if " submitted 2 " not in line]
        with open(os.path.join(chain, "history"), "w") as f:
            f.writelines(lines + ["2026-11-11T12:00:00 started 2 2 host\n"])
        self.fake.set_job("1", state="ended")
        self.fake.set_job("2", state="running")
        self.chainrun("stop", chain)
        self.assertEqual(self.fake.log()[-1], "cancel 2")


if __name__ == "__main__":
    unittest.main()
