ProofPay: AI-Judged Freelance Escrow (real GEN)

A client locks real GEN in a GenLayer Intelligent Contract. An AI judge scores the freelancer's work. A passing score pays the freelancer. A failing score keeps the money locked until the freelancer appeals or gives up, and the client can then get a refund.

Files
contracts/proofpay_escrow.py: the Intelligent Contract (deploy this one)
index.html: the app that calls the contract
tests/test_proofpay_escrow.py and tests/genlayer.py: automated tests
Escrow lifecycle
Fund: the client calls create_job with GEN attached. The GEN is held by the contract.
Work: the freelancer calls submit_work with a public link.
Judge: evaluate scores the work from 0 to 100 using an LLM with validator consensus.
Release: a score of 70 or more marks the job ACCEPTED and sends the locked GEN to the freelancer.
Hold: a lower score marks the job REJECTED. The GEN stays locked.
Appeal: the freelancer can appeal once with appeal, then the work is judged again.
Refund:
cancel_job: the client gets the GEN back before any work is submitted.
concede: the freelancer gives up on a rejected job and the client is refunded.
refund: the client claims the GEN after a rejection that was already appealed.

State is always updated before money moves, so a job can never be paid or refunded twice.

Contract
Network: GenLayer Studio
Address: 0x581CE42D6E205817C47A1e502857E36aF6C0e69D
Methods: create_job (payable), submit_work, evaluate, appeal, cancel_job, refund, concede, get_job
Tests

The tests cover funding, release, hold, appeal, every refund path, wrong callers, broken judge answers, double-spend attempts, and money conservation.

pip install pytest
pytest tests -q

They run the contract logic against a small simulated GenLayer runtime (tests/genlayer.py) with a scripted AI judge, so they are fast and need no network.

App

Open the live link, click Get test GEN if needed, create a job with an amount, submit a public link, and click Evaluate with AI.
