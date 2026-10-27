# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json


@gl.contract_interface
class _Wallet:
    class View:
        pass

    class Write:
        pass


PASS_SCORE = 70


class ProofPayEscrow(gl.Contract):
    """Freelance escrow with real GEN. The client locks funds when creating a
    job. An AI judge scores the delivered work. A passing score pays the
    freelancer. A failing score keeps the funds locked until the freelancer
    appeals, gives up, or the client claims a refund after the appeal."""

    jobs: TreeMap[str, str]
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
    ) -> str:
        amount = int(gl.message.value)
        if amount <= 0:
            raise Exception("Send GEN with this call to fund the escrow")
        freelancer = freelancer.strip().lower()
        if freelancer != "" and (len(freelancer) != 42 or not freelancer.startswith("0x")):
            raise Exception("Freelancer must be an address like 0x...")

        job_id = str(self.job_count)
        self._save(job_id, {
            "title": title,
            "brief": brief,
            "criteria": criteria,
            "amount": amount,
            "client": self._me(),
            "freelancer": freelancer,
            "submitter": "",
            "deliverable": "",
            "status": "OPEN",
            "score": 0,
            "reason": "",
            "escrow": "FUNDED",
            "appeal": "",
            "appeals": 0,
        })
        self.job_count = u256(int(self.job_count) + 1)
        return job_id

    @gl.public.write
    def submit_work(self, job_id: str, deliverable_url: str) -> None:
        job = self._load(job_id)
        me = self._me()
        if job["freelancer"] != "" and me != job["freelancer"]:
            raise Exception("Only the freelancer can submit work")
        if job["status"] != "OPEN":
            raise Exception("Work was already submitted")
        job["deliverable"] = deliverable_url
        job["submitter"] = me
        job["status"] = "SUBMITTED"
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
        job["appeal"] = message
        job["appeals"] = 1
        job["status"] = "APPEALED"
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
        criteria = job["criteria"]
        appeal_text = job["appeal"]

        def judge() -> str:
            page = gl.nondet.web.render(url, mode="text")
            prompt = f"""
You are a fair judge for a freelance job.
Brief: {brief}
Acceptance criteria: {criteria}
Freelancer appeal (may be empty): {appeal_text}
Deliverable content: {page[:4000]}

Score how well the deliverable meets the brief and the acceptance criteria from 0 to 100.
70 or more means the work meets the brief. Below 70 means it does not.
Reply only with JSON: {{"score": 0-100, "reason": "one short sentence"}}
"""
            return gl.nondet.exec_prompt(prompt)

        result = gl.eq_principle.prompt_comparative(
            judge,
            "The two scores must be within 15 points of each other and on the same side of 70",
        )
        clean = result.replace("```json", "").replace("```", "").strip()
        verdict = json.loads(clean)

        score = max(0, min(100, int(float(verdict["score"]))))
        job["score"] = score
        job["reason"] = str(verdict["reason"])

        if score >= PASS_SCORE:
            # settle first, then pay: the state can never pay twice
            job["status"] = "ACCEPTED"
            job["escrow"] = "RELEASED"
            self._save(job_id, job)
            self._pay(job["submitter"], job["amount"])
        else:
            job["status"] = "REJECTED"
            self._save(job_id, job)
        return job["status"]

    # ---------- refunds ----------

    @gl.public.write
    def cancel_job(self, job_id: str) -> None:
        """Client takes the money back before any work was submitted."""
        job = self._load(job_id)
        if self._me() != job["client"]:
            raise Exception("Only the client can cancel")
        if job["status"] != "OPEN" or job["escrow"] != "FUNDED":
            raise Exception("Only a job with no submitted work can be cancelled")
        job["status"] = "CANCELLED"
        job["escrow"] = "REFUNDED"
        self._save(job_id, job)
        self._pay(job["client"], job["amount"])

    @gl.public.write
    def refund(self, job_id: str) -> None:
        """Client claims the money back after a rejection that was already appealed."""
        job = self._load(job_id)
        if self._me() != job["client"]:
            raise Exception("Only the client can claim a refund")
        if job["status"] != "REJECTED" or job["escrow"] != "FUNDED":
            raise Exception("Refund is only possible after a final rejection")
        if job["appeals"] < 1:
            raise Exception("The freelancer can still appeal this rejection")
        job["escrow"] = "REFUNDED"
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
        self._save(job_id, job)
        self._pay(job["client"], job["amount"])

    # ---------- views ----------

    @gl.public.view
    def get_job(self, job_id: str) -> str:
        return self.jobs[job_id]
