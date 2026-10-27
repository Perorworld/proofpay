import copy
import importlib.util
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import genlayer as rt  # the simulated runtime in this folder

CONTRACT_PATH = os.path.join(HERE, "..", "contracts", "proofpay_escrow.py")
spec = importlib.util.spec_from_file_location("proofpay_escrow", CONTRACT_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

CLIENT = "0x" + "a1" * 20
FREELANCER = "0x" + "b2" * 20
STRANGER = "0x" + "c3" * 20
ESCROW = 5 * 10**18
START = 100 * 10**18
URL = "https://example.com/work"


def tx(c, name, *args, sender, value=0):
    """Run one transaction. Any error reverts all state and balances."""
    snap_state = copy.deepcopy(c.__dict__)
    snap_ledger = dict(rt.ledger)
    rt.gl.message.sender_address = rt.Address(sender)
    rt.gl.message.value = value
    fn = getattr(c, name)
    kind = getattr(fn, "_kind", None)
    try:
        if value:
            if kind != "payable":
                raise Exception("this method does not accept GEN")
            rt.move(sender, rt.ADDRESS, value)
        return fn(*args)
    except Exception:
        c.__dict__.clear()
        c.__dict__.update(snap_state)
        rt.ledger.clear()
        rt.ledger.update(snap_ledger)
        raise


def judge(score, reason="ok"):
    rt.gl.nondet.judge_reply = json.dumps({"score": score, "reason": reason})


def bal(addr):
    return rt.ledger.get(addr, 0)


def job(c, job_id="0"):
    return json.loads(c.get_job(job_id))


@pytest.fixture
def c():
    rt.ledger.clear()
    rt.ledger.update({CLIENT: START, FREELANCER: START, STRANGER: START})
    rt.gl.nondet.web.pages.clear()
    rt.gl.nondet.web.pages[URL] = "some delivered work"
    return module.ProofPayEscrow()


def make_job(c, freelancer=FREELANCER, value=ESCROW):
    return tx(c, "create_job", "Logo", "Make a logo", "Mention coffee",
              freelancer, sender=CLIENT, value=value)


def submitted_job(c, freelancer=FREELANCER, who=FREELANCER):
    make_job(c, freelancer)
    tx(c, "submit_work", "0", URL, sender=who)


def rejected_job(c):
    submitted_job(c)
    judge(30, "does not match")
    tx(c, "evaluate", "0", sender=FREELANCER)


# ---------------- funding ----------------

def test_create_job_locks_funds_in_the_contract(c):
    make_job(c)
    assert bal(rt.ADDRESS) == ESCROW
    assert bal(CLIENT) == START - ESCROW
    j = job(c)
    assert j["escrow"] == "FUNDED" and j["amount"] == ESCROW and j["status"] == "OPEN"


def test_create_job_without_funds_fails(c):
    with pytest.raises(Exception, match="fund the escrow"):
        tx(c, "create_job", "t", "b", "c", FREELANCER, sender=CLIENT, value=0)
    assert int(c.job_count) == 0 and bal(rt.ADDRESS) == 0


def test_create_job_with_more_than_balance_fails(c):
    with pytest.raises(Exception):
        make_job(c, value=START + 1)
    assert int(c.job_count) == 0 and bal(CLIENT) == START


def test_create_job_with_bad_freelancer_address_fails_and_refunds(c):
    with pytest.raises(Exception, match="Freelancer must be an address"):
        make_job(c, freelancer="not-an-address")
    assert bal(CLIENT) == START and bal(rt.ADDRESS) == 0


def test_methods_that_are_not_payable_reject_funds(c):
    make_job(c)
    with pytest.raises(Exception, match="does not accept GEN"):
        tx(c, "submit_work", "0", URL, sender=FREELANCER, value=1)
    assert bal(rt.ADDRESS) == ESCROW


# ---------------- settlement (release) ----------------

def test_accepted_work_pays_the_freelancer(c):
    submitted_job(c)
    judge(85, "meets the brief")
    assert tx(c, "evaluate", "0", sender=CLIENT) == "ACCEPTED"
    assert bal(FREELANCER) == START + ESCROW
    assert bal(rt.ADDRESS) == 0
    j = job(c)
    assert j["escrow"] == "RELEASED" and j["score"] == 85


def test_open_job_pays_whoever_submitted(c):
    make_job(c, freelancer="")
    tx(c, "submit_work", "0", URL, sender=STRANGER)
    judge(90)
    tx(c, "evaluate", "0", sender=CLIENT)
    assert bal(STRANGER) == START + ESCROW and bal(rt.ADDRESS) == 0


def test_score_boundary_70_pays_and_69_does_not(c):
    submitted_job(c)
    judge(70)
    assert tx(c, "evaluate", "0", sender=CLIENT) == "ACCEPTED"
    rt.ledger.clear()
    rt.ledger.update({CLIENT: START, FREELANCER: START})
    c2 = module.ProofPayEscrow()
    submitted_job(c2)
    judge(69)
    assert tx(c2, "evaluate", "0", sender=CLIENT) == "REJECTED"
    assert bal(rt.ADDRESS) == ESCROW


def test_scores_are_clamped_to_0_100(c):
    submitted_job(c)
    judge(150)
    tx(c, "evaluate", "0", sender=CLIENT)
    assert job(c)["score"] == 100


def test_appeal_can_turn_a_rejection_into_payment(c):
    rejected_job(c)
    tx(c, "appeal", "0", "I did mention coffee", sender=FREELANCER)
    judge(88, "appeal accepted")
    assert tx(c, "evaluate", "0", sender=FREELANCER) == "ACCEPTED"
    assert bal(FREELANCER) == START + ESCROW and bal(rt.ADDRESS) == 0


# ---------------- failure paths: money stays safe ----------------

def test_rejected_work_keeps_funds_locked(c):
    rejected_job(c)
    assert bal(rt.ADDRESS) == ESCROW
    assert bal(FREELANCER) == START
    assert job(c)["escrow"] == "FUNDED"


def test_only_the_named_freelancer_can_submit(c):
    make_job(c)
    with pytest.raises(Exception, match="Only the freelancer"):
        tx(c, "submit_work", "0", URL, sender=STRANGER)
    assert job(c)["status"] == "OPEN"


def test_strangers_cannot_trigger_a_review(c):
    submitted_job(c)
    judge(99)
    with pytest.raises(Exception, match="Only the client or the freelancer"):
        tx(c, "evaluate", "0", sender=STRANGER)
    assert bal(STRANGER) == START and bal(rt.ADDRESS) == ESCROW


def test_cannot_evaluate_before_work_is_submitted(c):
    make_job(c)
    with pytest.raises(Exception, match="no work waiting"):
        tx(c, "evaluate", "0", sender=CLIENT)


def test_unknown_job_fails(c):
    with pytest.raises(Exception, match="Job not found"):
        tx(c, "submit_work", "99", URL, sender=FREELANCER)


def test_broken_judge_reply_reverts_and_keeps_funds_locked(c):
    submitted_job(c)
    rt.gl.nondet.judge_reply = "this is not json"
    with pytest.raises(Exception):
        tx(c, "evaluate", "0", sender=CLIENT)
    assert job(c)["status"] == "SUBMITTED"
    assert bal(rt.ADDRESS) == ESCROW and bal(FREELANCER) == START


def test_unreachable_deliverable_reverts_and_keeps_funds_locked(c):
    make_job(c)
    tx(c, "submit_work", "0", "https://nowhere.invalid", sender=FREELANCER)
    judge(95)
    with pytest.raises(Exception, match="unreachable"):
        tx(c, "evaluate", "0", sender=CLIENT)
    assert bal(rt.ADDRESS) == ESCROW and job(c)["status"] == "SUBMITTED"


def test_appeal_rules(c):
    submitted_job(c)
    with pytest.raises(Exception, match="Only rejected work"):
        tx(c, "appeal", "0", "please", sender=FREELANCER)
    rt.ledger.update({})
    c2 = module.ProofPayEscrow()
    rejected_job(c2)
    with pytest.raises(Exception, match="Only the freelancer"):
        tx(c2, "appeal", "0", "please", sender=STRANGER)
    tx(c2, "appeal", "0", "please", sender=FREELANCER)
    judge(20)
    tx(c2, "evaluate", "0", sender=FREELANCER)
    with pytest.raises(Exception, match="already appealed"):
        tx(c2, "appeal", "0", "again", sender=FREELANCER)


# ---------------- refunds ----------------

def test_client_can_cancel_before_any_work_is_submitted(c):
    make_job(c)
    tx(c, "cancel_job", "0", sender=CLIENT)
    assert bal(CLIENT) == START and bal(rt.ADDRESS) == 0
    j = job(c)
    assert j["status"] == "CANCELLED" and j["escrow"] == "REFUNDED"


def test_only_the_client_can_cancel(c):
    make_job(c)
    with pytest.raises(Exception, match="Only the client"):
        tx(c, "cancel_job", "0", sender=FREELANCER)
    assert bal(rt.ADDRESS) == ESCROW


def test_cannot_cancel_after_work_is_submitted(c):
    submitted_job(c)
    with pytest.raises(Exception, match="no submitted work"):
        tx(c, "cancel_job", "0", sender=CLIENT)
    assert bal(rt.ADDRESS) == ESCROW


def test_client_refund_after_final_rejection(c):
    rejected_job(c)
    tx(c, "appeal", "0", "please recheck", sender=FREELANCER)
    judge(25, "still not matching")
    tx(c, "evaluate", "0", sender=FREELANCER)
    tx(c, "refund", "0", sender=CLIENT)
    assert bal(CLIENT) == START and bal(rt.ADDRESS) == 0
    assert job(c)["escrow"] == "REFUNDED"


def test_client_cannot_refund_while_an_appeal_is_still_possible(c):
    rejected_job(c)
    with pytest.raises(Exception, match="can still appeal"):
        tx(c, "refund", "0", sender=CLIENT)
    assert bal(rt.ADDRESS) == ESCROW


def test_only_the_client_can_claim_a_refund(c):
    rejected_job(c)
    tx(c, "appeal", "0", "x", sender=FREELANCER)
    judge(10)
    tx(c, "evaluate", "0", sender=FREELANCER)
    with pytest.raises(Exception, match="Only the client"):
        tx(c, "refund", "0", sender=FREELANCER)


def test_freelancer_can_give_up_and_client_gets_money_back(c):
    rejected_job(c)
    tx(c, "concede", "0", sender=FREELANCER)
    assert bal(CLIENT) == START and bal(rt.ADDRESS) == 0
    assert job(c)["escrow"] == "REFUNDED"


def test_concede_only_works_for_the_freelancer_on_rejected_jobs(c):
    submitted_job(c)
    with pytest.raises(Exception, match="Only a rejected job"):
        tx(c, "concede", "0", sender=FREELANCER)
    rejected = module.ProofPayEscrow()
    rt.ledger.update({CLIENT: START, FREELANCER: START})
    rt.ledger[rt.ADDRESS] = ESCROW  # funds of the first contract stay put
    rejected_job(rejected)
    with pytest.raises(Exception, match="Only the freelancer"):
        tx(rejected, "concede", "0", sender=STRANGER)


# ---------------- no double spending ----------------

def test_nothing_can_move_after_payment_was_released(c):
    submitted_job(c)
    judge(95)
    tx(c, "evaluate", "0", sender=CLIENT)
    after = dict(rt.ledger)
    for name, who in [("cancel_job", CLIENT), ("refund", CLIENT), ("concede", FREELANCER)]:
        with pytest.raises(Exception):
            tx(c, name, "0", sender=who)
    with pytest.raises(Exception):
        tx(c, "evaluate", "0", sender=CLIENT)
    with pytest.raises(Exception):
        tx(c, "appeal", "0", "x", sender=FREELANCER)
    assert rt.ledger == after


def test_nothing_can_move_after_a_refund(c):
    rejected_job(c)
    tx(c, "concede", "0", sender=FREELANCER)
    after = dict(rt.ledger)
    for name, who in [("cancel_job", CLIENT), ("refund", CLIENT), ("concede", FREELANCER)]:
        with pytest.raises(Exception):
            tx(c, name, "0", sender=who)
    with pytest.raises(Exception):
        tx(c, "appeal", "0", "x", sender=FREELANCER)
    assert rt.ledger == after


def test_total_money_is_conserved_across_a_full_run(c):
    total = sum(rt.ledger.values())
    make_job(c)
    assert sum(rt.ledger.values()) == total
    tx(c, "submit_work", "0", URL, sender=FREELANCER)
    judge(10)
    tx(c, "evaluate", "0", sender=CLIENT)
    tx(c, "appeal", "0", "x", sender=FREELANCER)
    judge(95)
    tx(c, "evaluate", "0", sender=CLIENT)
    assert sum(rt.ledger.values()) == total


def test_two_jobs_hold_separate_funds(c):
    make_job(c)
    make_job(c, value=2 * 10**18)
    assert bal(rt.ADDRESS) == ESCROW + 2 * 10**18
    tx(c, "cancel_job", "1", sender=CLIENT)
    assert bal(rt.ADDRESS) == ESCROW
    assert job(c, "0")["escrow"] == "FUNDED" and job(c, "1")["escrow"] == "REFUNDED"
