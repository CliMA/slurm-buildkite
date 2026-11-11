"""The fake scheduler for the chainrun tests.

chainrun loads it when CHAINRUN_SCHEDULER is "fake:DIR" and this directory is on PYTHONPATH.
It records every submit and cancel in DIR/log and answers queries from DIR/jobs.json, which
the test edits to move jobs between states. A file DIR/refuse makes submit fail with the
file's content as the message, DIR/cancel_fails makes cancel fail.
"""
import json
import os


class Fake:
    def __init__(self, directory):
        self.dir = directory
        os.makedirs(directory, exist_ok=True)

    def jobs(self):
        try:
            with open(os.path.join(self.dir, "jobs.json")) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def set_job(self, job_id, **fields):
        jobs = self.jobs()
        jobs.setdefault(job_id, {"state": "queued"}).update(fields)
        with open(os.path.join(self.dir, "jobs.json"), "w") as f:
            json.dump(jobs, f)

    def log(self):
        with open(os.path.join(self.dir, "log")) as f:
            return f.read().splitlines()

    def record(self, line):
        with open(os.path.join(self.dir, "log"), "a") as f:
            f.write(line + "\n")

    def job_id(self):
        return os.environ.get("CHAINRUN_FAKE_JOB_ID")

    def submit(self, batch, options, after=None, cwd=None, env=None):
        refuse = os.path.join(self.dir, "refuse")
        if os.path.exists(refuse):
            raise RuntimeError(open(refuse).read())
        job_id = str(len(self.jobs()) + 1)
        self.set_job(job_id, batch=batch, after=after, cwd=cwd, env=env)
        self.record("submit %s after=%s" % (job_id, after))
        return job_id

    def cancel(self, job_id):
        if os.path.exists(os.path.join(self.dir, "cancel_fails")):
            raise RuntimeError("the fake scheduler refuses the cancel")
        self.record("cancel " + job_id)
        self.set_job(job_id, state="ended")

    def query(self, job_id):
        return self.jobs().get(job_id, {"state": "unknown"})["state"]
