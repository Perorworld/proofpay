# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
from datetime import datetime, timezone
import json


@gl.contract_interface
class _Wallet:
    class View:
        pass

    class Write:
        pass


PASS_SCORE = 70
MAX_CRITERIA = 8
MAX_MINUTES = 60 * 24 * 365


def _now() -> int:
    # In GenVM this is the transaction time, the same on every validator
    return int(datetime.now(timezone.utc).timestamp())


def _blank_rep() -> dict:
    return {
        "jobs": 0,          # jobs created as a client
        "funded": 0,        # total GEN locked as a client (in wei)
        "evals": 0,         # times a freelancer's work was judged
        "score_sum": 0,     # sum of those scores
        "completed": 0,     # jobs accepted
        "rejected": 0,      # judgments below the pass mark
        "appeals_won": 0,   # accepted only after an appeal
        "earned": 0,        # GEN paid out as a freelancer (in wei)
    }


class ProofPayEscrow(gl.Contract):
    """Freelance escrow with real GEN, deadlines, per-criterion AI scoring,
    on-chain reputation and a full activity timeline for every job."""

    jobs: TreeMap[str, str]
    reputation: TreeMap[str, str]
    job_count: u256

    def __init__(self):
        self.job_count = u256(0)

    # ---------- helpers ----------

    def _me(self) -> str:
        return str(gl.message.sender_address).lower()

    def _load(self, job_id: str) -> dict:
        if job_id not in self.jobs:
            raise Exception("Job not found")
        return json.loads(self.jobs[job_id])

    def _save(self, job_id: str, job: dict) -> None:
        self.jobs[job_id] = json.dumps(job)

    def _log(self, job: dict, text: str) -> None:
        job["events"].append({"t": _now(), "by": self._me(), "text": text})

    def _rep_add(self, addr: str, **changes) -> None:
        if addr == "":
            return
        rep = _blank_rep()
        if addr in self.reputation:
            rep.update(json.loads(self.reputation[addr]))
        for key, delta in changes.items():
            rep[key] = rep[key] + delta
        self.reputation[addr] = json.dumps(rep)

    def _pay(self, to: str, amount: int) -> None:
        _Wallet(Address(to)).emit_transfer(value=u256(amount))

    # ---------- lifecycle ----------

    @gl.public.write.payable
    def create_job(
        self,
        title: str,
        brief: str,
        criteria: str,
        freelancer: str,
        work_minutes: u256,
        appeal_minutes: u256,
    ) -> str:
        amount = int(gl.message.value)
        if amount <= 0:
            raise Exception("Send GEN with this call to fund the escrow")
        freelancer = freelancer.strip().lower()
        if freelancer != "" and (len(freelancer) != 42 or not freelancer.startswith("0x")):
            raise Exception("Freelancer must be an address like 0x...")
        lines = [x.strip() for x in criteria.split("\n") if x.strip() != ""]
        if len(lines) == 0:
            raise Exception("Add at least one acceptance criterion")
        if len(lines) > MAX_CRITERIA:
            raise Exception("Use at most 8 acceptance criteria")
        work = int(work_minutes)
        appeal_window = int(appeal_minutes)
        if work < 1 or work > MAX_MINUTES or appeal_window < 1 or appeal_window > MAX_MINUTES:
            raise Exception("Deadlines must be between 1 minute and 1 year")

        now = _now()
        job_id = str(self.job_count)
        job = {
            "title": title,
            "brief": brief,
            "criteria": "\n".join(lines),
            "amount": amount,
            "client": self._me(),
            "freelancer": freelancer,
            "submitter": "",
            "deliverable": "",
            "status": "OPEN",
            "escrow": "FUNDED",
            "score": 0,
            "reason": "",
            "results": [],
            "appeal": "",
            "appeals": 0,
            "created_at": now,
            "deadline": now + work * 60,
            "appeal_seconds": appeal_window * 60,
            "rejected_at": 0,
            "events": [],
        }
        self._log(job, "Job created and funds locked in escrow")
        self._save(job_id, job)
        self._rep_add(self._me(), jobs=1, funded=amount)
        self.job_count = u256(int(self.job_count) + 1)
        return job_id

    @gl.public.write
    def submit_work(self, job_id: str, deliverable_url: str) -> None:
        job = self._load(job_id)
        me = self._me()
        if job["freelancer"] != "" and me != job["freelancer"]:
            raise Exception("Only the freelancer can submit work")
        if job["status"] != "OPEN" or job["escrow"] != "FUNDED":
            raise Exception("Work was already submitted or the job is closed")
        if _now() > job["deadline"]:
            raise Exception("The deadline has passed")
        job["deliverable"] = deliverable_url
        job["submitter"] = me
        job["status"] = "SUBMITTED"
        self._log(job, "Work submitted")
        self._save(job_id, job)

    @gl.public.write
    def appeal(self, job_id: str, message: str) -> None:
        job = self._load(job_id)
        if self._me() != job["submitter"]:
            raise Exception("Only the freelancer who submitted can appeal")
        if job["status"] != "REJECTED" or job["escrow"] != "FUNDED":
            raise Exception("Only rejected work with funds still held can be appealed")
        if job["appeals"] >= 1:
            raise Exception("This job was already appealed once")
        if _now() > job["rejected_at"] + job["appeal_seconds"]:
            raise Exception("The appeal window has closed")
        job["appeal"] = message
        job["appeals"] = 1
        job["status"] = "APPEALED"
        self._log(job, "Freelancer appealed the rejection")
        self._save(job_id, job)

    @gl.public.write
    def evaluate(self, job_id: str) -> str:
        job = self._load(job_id)
        me = self._me()
        if me not in (job["client"], job["freelancer"], job["submitter"]):
            raise Exception("Only the client or the freelancer can request a review")
        if job["status"] not in ("SUBMITTED", "APPEALED"):
            raise Exception("There is no work waiting for review")
        if job["escrow"] != "FUNDED":
            raise Exception("Escrow is no longer holding funds")

        url = job["deliverable"]
        brief = job["brief"]
        criteria_lines = job["criteria"].split("\n")
        numbered = "\n".join([f"{i + 1}. {line}" for i, line in enumerate(criteria_lines)])
        appeal_text = job["appeal"]

        def judge() -> str:
            page = gl.nondet.web.render(url, mode="text")
            prompt = f"""
You are a fair judge for a freelance job.
Brief: {brief}
Acceptance criteria, one per line:
{numbered}
Freelancer appeal (may be empty): {appeal_text}
Deliverable content: {page[:4000]}

Score the deliverable on EACH criterion from 0 to 100.
Reply only with JSON in exactly this shape:
{{"results": [{{"criterion": "the criterion text", "score": 0-100, "note": "one short sentence"}}], "reason": "one short overall sentence"}}
"""
            return gl.nondet.exec_prompt(prompt)

        result = gl.eq_principle.prompt_comparative(
            judge,
            "The average of the criterion scores must be within 15 points and on the same side of 70",
        )
        clean = result.replace("```json", "").replace("```", "").strip()
        verdict = json.loads(clean)

        items = verdict["results"]
        if not isinstance(items, list) or len(items) == 0:
            raise Exception("The judge returned no criterion results")
        results = []
        for item in items[:MAX_CRITERIA]:
            results.append({
                "criterion": str(item["criterion"])[:200],
                "score": max(0, min(100, int(float(item["score"])))),
                "note": str(item["note"])[:300],
            })
        score = sum([r["score"] for r in results]) // len(results)

        was_appealed = job["appeals"] >= 1
        job["results"] = results
        job["score"] = score
        job["reason"] = str(verdict["reason"])[:300]
        who = job["submitter"]

        if score >= PASS_SCORE:
            # settle first, then pay: the state can never pay twice
            job["status"] = "ACCEPTED"
            job["escrow"] = "RELEASED"
            self._log(job, f"Judged {score}/100: accepted, escrow paid to the freelancer")
            self._save(job_id, job)
            self._rep_add(
                who, evals=1, score_sum=score, completed=1, earned=job["amount"],
                appeals_won=1 if was_appealed else 0,
            )
            self._pay(who, job["amount"])
        else:
            job["status"] = "REJECTED"
            job["rejected_at"] = _now()
            self._log(job, f"Judged {score}/100: rejected, funds stay locked")
            self._save(job_id, job)
            self._rep_add(who, evals=1, score_sum=score, rejected=1)
        return job["status"]

    # ---------- refunds ----------

    @gl.public.write
    def cancel_job(self, job_id: str) -> None:
        """Client takes the money back when no work was submitted. A named
        freelancer keeps the right to deliver until the deadline."""
        job = self._load(job_id)
        if self._me() != job["client"]:
            raise Exception("Only the client can cancel")
        if job["status"] != "OPEN" or job["escrow"] != "FUNDED":
            raise Exception("Only a job with no submitted work can be cancelled")
        if job["freelancer"] != "" and _now() <= job["deadline"]:
            raise Exception("The freelancer still has until the deadline to deliver")
        job["status"] = "CANCELLED"
        job["escrow"] = "REFUNDED"
        self._log(job, "Job cancelled, escrow refunded to the client")
        self._save(job_id, job)
        self._pay(job["client"], job["amount"])

    @gl.public.write
    def refund(self, job_id: str) -> None:
        """Client claims the money back after a rejection that was appealed,
        or after the appeal window ended with no appeal."""
        job = self._load(job_id)
        if self._me() != job["client"]:
            raise Exception("Only the client can claim a refund")
        if job["status"] != "REJECTED" or job["escrow"] != "FUNDED":
            raise Exception("Refund is only possible after a final rejection")
        window_over = _now() > job["rejected_at"] + job["appeal_seconds"]
        if job["appeals"] < 1 and not window_over:
            raise Exception("The freelancer can still appeal this rejection")
        job["escrow"] = "REFUNDED"
        self._log(job, "Refund claimed, escrow returned to the client")
        self._save(job_id, job)
        self._pay(job["client"], job["amount"])

    @gl.public.write
    def concede(self, job_id: str) -> None:
        """Freelancer gives up on a rejected job, so the client is refunded."""
        job = self._load(job_id)
        if self._me() != job["submitter"]:
            raise Exception("Only the freelancer who submitted can give up")
        if job["status"] != "REJECTED" or job["escrow"] != "FUNDED":
            raise Exception("Only a rejected job with funds held can be given up")
        job["escrow"] = "REFUNDED"
        self._log(job, "Freelancer gave up, escrow returned to the client")
        self._save(job_id, job)
        self._pay(job["client"], job["amount"])

    # ---------- views ----------

    @gl.public.view
    def get_job(self, job_id: str) -> str:
        return self.jobs[job_id]

    @gl.public.view
    def get_reputation(self, addr: str) -> str:
        key = addr.strip().lower()
        if key in self.reputation:
            rep = _blank_rep()
            rep.update(json.loads(self.reputation[key]))
            return json.dumps(rep)
        return json.dumps(_blank_rep())
