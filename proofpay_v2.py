# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json


class ProofPay(gl.Contract):
    jobs: TreeMap[str, str]
    job_count: u256

    def __init__(self):
        self.job_count = u256(0)

    def _me(self) -> str:
        return str(gl.message.sender_address).lower()

    @gl.public.write
    def create_job(
        self,
        title: str,
        brief: str,
        criteria: str,
        amount: u256,
        freelancer: str,
    ) -> str:
        job_id = str(self.job_count)
        self.jobs[job_id] = json.dumps({
            "title": title,
            "brief": brief,
            "criteria": criteria,
            "amount": int(amount),
            "client": self._me(),
            "freelancer": freelancer.strip().lower(),
            "submitter": "",
            "deliverable": "",
            "status": "OPEN",
            "score": 0,
            "reason": "",
            "payment": "HELD",
            "appeal": "",
            "appeals": 0,
        })
        self.job_count = u256(int(self.job_count) + 1)
        return job_id

    @gl.public.write
    def submit_work(self, job_id: str, deliverable_url: str) -> None:
        job = json.loads(self.jobs[job_id])
        me = self._me()
        if job["freelancer"] != "" and me != job["freelancer"]:
            raise Exception("Only the freelancer can submit work")
        if job["status"] != "OPEN":
            raise Exception("Work was already submitted")
        job["deliverable"] = deliverable_url
        job["submitter"] = me
        job["status"] = "SUBMITTED"
        self.jobs[job_id] = json.dumps(job)

    @gl.public.write
    def appeal(self, job_id: str, message: str) -> None:
        job = json.loads(self.jobs[job_id])
        me = self._me()
        if me != job["submitter"]:
            raise Exception("Only the freelancer who submitted can appeal")
        if job["status"] != "REJECTED":
            raise Exception("Only rejected work can be appealed")
        if job["appeals"] >= 1:
            raise Exception("This job was already appealed once")
        job["appeal"] = message
        job["appeals"] = 1
        job["status"] = "APPEALED"
        self.jobs[job_id] = json.dumps(job)

    @gl.public.write
    def evaluate(self, job_id: str) -> str:
        job = json.loads(self.jobs[job_id])
        me = self._me()
        if me not in (job["client"], job["freelancer"], job["submitter"]):
            raise Exception("Only the client or the freelancer can request a review")
        if job["status"] not in ("SUBMITTED", "APPEALED"):
            raise Exception("There is no work waiting for review")

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

        score = int(float(verdict["score"]))
        score = max(0, min(100, score))
        accepted = score >= 70

        job["score"] = score
        job["reason"] = verdict["reason"]
        job["status"] = "ACCEPTED" if accepted else "REJECTED"
        job["payment"] = "RELEASED" if accepted else "HELD"
        self.jobs[job_id] = json.dumps(job)
        return job["status"]

    @gl.public.view
    def get_job(self, job_id: str) -> str:
        return self.jobs[job_id]
