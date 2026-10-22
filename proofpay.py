# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json


class ProofPay(gl.Contract):
    jobs: TreeMap[str, str]
    job_count: u256

    def __init__(self):
        self.job_count = u256(0)

    @gl.public.write
    def create_job(self, title: str, brief: str, criteria: str, amount: u256) -> str:
        job_id = str(self.job_count)
        self.jobs[job_id] = json.dumps({
            "title": title,
            "brief": brief,
            "criteria": criteria,
            "amount": int(amount),
            "client": str(gl.message.sender_address),
            "deliverable": "",
            "status": "OPEN",
            "reason": "",
            "payment": "HELD",
        })
        self.job_count = u256(int(self.job_count) + 1)
        return job_id

    @gl.public.write
    def submit_work(self, job_id: str, deliverable_url: str) -> None:
        job = json.loads(self.jobs[job_id])
        job["deliverable"] = deliverable_url
        job["status"] = "SUBMITTED"
        self.jobs[job_id] = json.dumps(job)

    @gl.public.write
    def evaluate(self, job_id: str) -> str:
        job = json.loads(self.jobs[job_id])
        url = job["deliverable"]
        brief = job["brief"]
        criteria = job["criteria"]

        def judge() -> str:
            page = gl.nondet.web.render(url, mode="text")
            prompt = f"""
You are a fair judge for a freelance job.
Brief: {brief}
Acceptance criteria: {criteria}
Deliverable content: {page[:4000]}

Does the deliverable meet the brief and criteria?
Reply only with JSON: {{"decision": "ACCEPTED" or "REJECTED", "reason": "one short sentence"}}
"""
            return gl.nondet.exec_prompt(prompt)

        result = gl.eq_principle.prompt_comparative(
            judge, "The decision field must be the same"
        )
        clean = result.replace("```json", "").replace("```", "").strip()
        verdict = json.loads(clean)

        job["status"] = verdict["decision"]
        job["reason"] = verdict["reason"]
        job["payment"] = "RELEASED" if verdict["decision"] == "ACCEPTED" else "HELD"
        self.jobs[job_id] = json.dumps(job)
        return job["status"]

    @gl.public.view
    def get_job(self, job_id: str) -> str:
        return self.jobs[job_id]