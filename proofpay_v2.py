# ProofPay: Intelligent Freelance Escrow

Freelancers and clients often disagree about whether finished work meets the original brief. ProofPay fixes this with an AI judge on GenLayer.

## How it works
1. The client creates a job with a brief and acceptance criteria before work starts.
2. The freelancer submits a link to the finished work.
3. A GenLayer Intelligent Contract reads the work and judges it against the brief. Validators reach consensus on the result.
4. The verdict (accepted or rejected) and a short reason are recorded on-chain.
5. Payment is marked as released if accepted, or held if rejected (simulated).
### New in version 2
- **Score out of 100:** the AI judge gives a score. 70 or more means the work is accepted.
- **One appeal:** if work is rejected, the freelancer can explain why and ask for one more review.
- **Roles:** the client names the freelancer, and only that freelancer can submit work or appeal.

## Why GenLayer
The contract uses an LLM and live web data to make a subjective decision, then reaches agreement between validators. A normal smart contract can't do this.

## What's in this repo
- `proofpay.py`: the Intelligent Contract
- `proofpay.html`: the app that talks to the contract

## Contract
- Network: GenLayer Studio
- Address: `0x51BcE089F35e7C9C8a030a855f89999578aD8b91`
- Methods: `create_job`, `submit_work`, `evaluate`, `get_job`

## Run the app
1. Open `proofpay.html` in your browser.
2. Paste the contract address and click Connect.
3. Create a job, submit a public link, and click Evaluate with AI.

## Demo
Add your screenshots or video link here.

Built by Francis Ogbonaya (@PEROR250)
