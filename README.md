# ProofPay v2: AI-Judged Freelance Escrow with real GEN

A client locks real GEN in a GenLayer Intelligent Contract. An AI judge scores each acceptance criterion. A passing average pays the freelancer, a failing one keeps the money locked, and deadlines, appeals and refunds make sure funds never get stuck.

## What is new in v2
- **Deadlines and auto-settlement:** every job has a delivery deadline and an appeal window. Late work is refused, the client can cancel after a missed deadline, and a rejection with no appeal can be refunded once the window ends.
- **Per-criterion scoring:** the client lists up to 8 criteria. The AI scores each one from 0 to 100 and the average decides the result (70 or more is accepted).
- **On-chain reputation:** the contract tracks jobs created and funded for clients, and jobs completed, rejections, average score, appeals won and GEN earned for freelancers.
- **Activity timeline:** every job records each step with the time and the address that did it.
- **Wallet login:** the app works with any browser wallet (MetaMask, Rabby, Coinbase Wallet, Brave and others), optional WalletConnect for phone wallets, and built-in test accounts.
- **Public testnet:** the app can switch between GenLayer Studio and the Bradbury testnet.

## Files
- `contracts/proofpay_escrow_v2.py`: the Intelligent Contract
- `index.html`: the app
- `tests/`: automated tests (`test_proofpay_escrow_v2.py`, plus the earlier suite and the `genlayer.py` test runtime)

## Escrow lifecycle
1. **Fund:** `create_job` is payable. The client attaches GEN, sets the criteria, a delivery time and an appeal window, and can name the freelancer.
2. **Deliver:** `submit_work` records a public link, only before the deadline and only from the named freelancer.
3. **Judge:** `evaluate` scores each criterion with an LLM and validator consensus.
4. **Release:** an average of 70 or more sends the locked GEN to the freelancer.
5. **Hold:** a lower average keeps the GEN locked.
6. **Appeal:** `appeal` (once, inside the appeal window) triggers a second review.
7. **Refund:** `cancel_job` (no work submitted; for a named freelancer only after the deadline), `concede` (the freelancer gives up), `refund` (the client, after an appeal or once the appeal window ends).

State is always saved before money moves, so a job can never be paid or refunded twice.

## Contract
- Studio address: `0x1bc926800b82B1555fcAF27d987D837627DEF20B`
- Bradbury address: `PASTE_BRADBURY_ADDRESS`
- Methods: `create_job` (payable), `submit_work`, `evaluate`, `appeal`, `cancel_job`, `refund`, `concede`, `get_job`, `get_reputation`

## Tests
```
pip install pytest
pytest tests -q
```
The tests cover funding, scoring, every refund path, deadlines and the appeal window, reputation, the timeline, wrong callers, broken judge answers, double-spend attempts and money conservation. They run the contract against a small simulated GenLayer runtime with a scripted judge and a controllable clock.
