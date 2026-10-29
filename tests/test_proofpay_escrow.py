import copy
import datetime as real_datetime
import importlib.util
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import genlayer as rt  # the simulated runtime in this folder

CONTRACT_PATH = os.path.join(HERE, "..", "contracts", "proofpay_escrow_v2.py")
spec = importlib.util.spec_from_file_location("proofpay_escrow_v2", CONTRACT_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# ---- a clock the tests control (the contract reads the transaction time) ----
CLOCK = [1_800_000_000]


class FakeDatetime:
    @staticmethod
    def now(tz=None):
        return real_datetime.datetime.fromtimestamp(CLOCK[0], tz)


module.datetime = FakeDatetime


def advance(minutes):
    CLOCK[0] += int(minutes * 60)


CLIENT = "0x" + "a1" * 20
FREELANCER = "0x" + "b2" * 20
STRANGER = "0x" + "c3" * 20
ESCROW = 5 * 10**18
START = 100 * 10**18
URL = "https://example.com/work"
CRITERIA = "Mentions coffee\nUses brown colors"
WORK_MIN = 120
APPEAL_MIN = 60


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


def judge(*scores, reason="ok"):
    rt.gl.nondet.judge_reply = json.dumps({
        "results": [{"criterion": f"c{i}", "score": s, "note": "n"} for i, s in enumerate(scores)],
        "reason": reason,
    })


def bal(addr):
    return rt.ledger.get(addr, 0)


def job(c, job_id="0"):
    return json.loads(c.get_job(job_id))


def rep(c, addr):
    return json.loads(c.get_reputation(addr))


@pytest.fixture
def c():
    CLOCK[0] = 1_800_000_000
    rt.ledger.clear()
    rt.ledger.update({CLIENT: START, FREELANCER: START, STRANGER: START})
    rt.gl.nondet.web.pages.clear()
    rt.gl.nondet.web.pages[URL] = "some delivered work"
    return module.ProofPayEscrow()


def make_job(c, freelancer=FREELANCER, value=ESCROW, criteria=CRITERIA,
             work=WORK_MIN, appeal=APPEAL_MIN):
    return tx(c, "create_job", "Logo", "Make a logo", criteria, freelancer,
              work, appeal, sender=CLIENT, value=value)


def submitted_job(c, freelancer=FREELANCER, who=FREELANCER):
    make_job(c, freelancer)
    tx(c, "submit_work", "0", URL, sender=who)


def rejected_job(c):
    submitted_job(c)
    judge(30, 20)
    tx(c, "evaluate", "0", sender=FREELANCER)


# ================= funding =================

def test_create_job_locks_funds_in_the_contract(c):
    make_job(c)
    assert bal(rt.ADDRESS) == ESCROW and bal(CLIENT) == START - ESCROW
    j = job(c)
    assert j["escrow"] == "FUNDED" and j["amount"] == ESCROW and j["status"] == "OPEN"


def test_create_job_without_funds_fails(c):
    with pytest.raises(Exception, match="fund the escrow"):
        make_job(c, value=0)
    assert int(c.job_count) == 0 and bal(rt.ADDRESS) == 0


def test_create_job_with_more_than_balance_fails(c):
    with pytest.raises(Exception):
        make_job(c, value=START + 1)
    assert int(c.job_count) == 0 and bal(CLIENT) == START


def test_create_job_rejects_bad_input_and_returns_the_funds(c):
    for kwargs, message in [
        ({"freelancer": "nope"}, "Freelancer must be an address"),
        ({"criteria": "  \n  "}, "at least one acceptance criterion"),
        ({"criteria": "\n".join(f"c{i}" for i in range(9))}, "at most 8"),
        ({"work": 0}, "Deadlines must be"),
        ({"appeal": 0}, "Deadlines must be"),
    ]:
        with pytest.raises(Exception, match=message):
            make_job(c, **kwargs)
        assert bal(CLIENT) == START and bal(rt.ADDRESS) == 0 and int(c.job_count) == 0


def test_non_payable_methods_reject_funds(c):
    make_job(c)
    with pytest.raises(Exception, match="does not accept GEN"):
        tx(c, "submit_work", "0", URL, sender=FREELANCER, value=1)
    assert bal(rt.ADDRESS) == ESCROW


# ================= per-criterion scoring and release =================

def test_score_is_the_average_of_the_criteria_and_results_are_stored(c):
    submitted_job(c)
    judge(90, 80, reason="good work")
    assert tx(c, "evaluate", "0", sender=CLIENT) == "ACCEPTED"
    j = job(c)
    assert j["score"] == 85 and j["reason"] == "good work"
    assert [r["score"] for r in j["results"]] == [90, 80]
    assert bal(FREELANCER) == START + ESCROW and bal(rt.ADDRESS) == 0
    assert j["escrow"] == "RELEASED"


def test_one_weak_criterion_can_pull_the_job_below_the_pass_mark(c):
    submitted_job(c)
    judge(100, 30)  # average 65
    assert tx(c, "evaluate", "0", sender=CLIENT) == "REJECTED"
    assert bal(rt.ADDRESS) == ESCROW and bal(FREELANCER) == START


def test_pass_mark_boundary(c):
    submitted_job(c)
    judge(70, 70)
    assert tx(c, "evaluate", "0", sender=CLIENT) == "ACCEPTED"
    CLOCK[0] += 1
    rt.ledger.clear()
    rt.ledger.update({CLIENT: START, FREELANCER: START})
    c2 = module.ProofPayEscrow()
    submitted_job(c2)
    judge(70, 69)  # average 69 (integer division)
    assert tx(c2, "evaluate", "0", sender=CLIENT) == "REJECTED"


def test_scores_are_clamped_to_0_100(c):
    submitted_job(c)
    judge(500, -20)
    tx(c, "evaluate", "0", sender=CLIENT)
    assert [r["score"] for r in job(c)["results"]] == [100, 0]


def test_open_job_pays_whoever_submitted(c):
    make_job(c, freelancer="")
    tx(c, "submit_work", "0", URL, sender=STRANGER)
    judge(90, 90)
    tx(c, "evaluate", "0", sender=CLIENT)
    assert bal(STRANGER) == START + ESCROW and bal(rt.ADDRESS) == 0


def test_broken_judge_answers_revert_and_keep_funds_locked(c):
    submitted_job(c)
    for reply in ["not json", json.dumps({"results": [], "reason": "x"}),
                  json.dumps({"reason": "no results key"})]:
        rt.gl.nondet.judge_reply = reply
        with pytest.raises(Exception):
            tx(c, "evaluate", "0", sender=CLIENT)
        assert job(c)["status"] == "SUBMITTED"
        assert bal(rt.ADDRESS) == ESCROW and bal(FREELANCER) == START


def test_unreachable_deliverable_reverts_and_keeps_funds_locked(c):
    make_job(c)
    tx(c, "submit_work", "0", "https://nowhere.invalid", sender=FREELANCER)
    judge(95, 95)
    with pytest.raises(Exception, match="unreachable"):
        tx(c, "evaluate", "0", sender=CLIENT)
    assert bal(rt.ADDRESS) == ESCROW and job(c)["status"] == "SUBMITTED"


# ================= roles =================

def test_only_the_named_freelancer_can_submit(c):
    make_job(c)
    with pytest.raises(Exception, match="Only the freelancer"):
        tx(c, "submit_work", "0", URL, sender=STRANGER)
    assert job(c)["status"] == "OPEN"


def test_strangers_cannot_review_appeal_refund_cancel_or_concede(c):
    rejected_job(c)
    for name, args in [("evaluate", ("0",)), ("appeal", ("0", "please")),
                       ("refund", ("0",)), ("cancel_job", ("0",)), ("concede", ("0",))]:
        with pytest.raises(Exception):
            tx(c, name, *args, sender=STRANGER)
    assert bal(rt.ADDRESS) == ESCROW


def test_cannot_evaluate_before_work_is_submitted(c):
    make_job(c)
    with pytest.raises(Exception, match="no work waiting"):
        tx(c, "evaluate", "0", sender=CLIENT)


def test_unknown_job_fails(c):
    with pytest.raises(Exception, match="Job not found"):
        tx(c, "submit_work", "99", URL, sender=FREELANCER)


# ================= deadlines =================

def test_cannot_submit_after_the_deadline(c):
    make_job(c)
    advance(WORK_MIN + 1)
    with pytest.raises(Exception, match="deadline has passed"):
        tx(c, "submit_work", "0", URL, sender=FREELANCER)
    assert job(c)["status"] == "OPEN"


def test_can_submit_right_up_to_the_deadline(c):
    make_job(c)
    advance(WORK_MIN)
    tx(c, "submit_work", "0", URL, sender=FREELANCER)
    assert job(c)["status"] == "SUBMITTED"


def test_client_cannot_cancel_a_named_job_before_the_deadline(c):
    make_job(c)
    advance(WORK_MIN - 1)
    with pytest.raises(Exception, match="until the deadline"):
        tx(c, "cancel_job", "0", sender=CLIENT)
    assert bal(rt.ADDRESS) == ESCROW


def test_client_can_cancel_a_named_job_after_the_deadline(c):
    make_job(c)
    advance(WORK_MIN + 1)
    tx(c, "cancel_job", "0", sender=CLIENT)
    assert bal(CLIENT) == START and bal(rt.ADDRESS) == 0
    j = job(c)
    assert j["status"] == "CANCELLED" and j["escrow"] == "REFUNDED"


def test_client_can_cancel_an_open_job_any_time_before_work(c):
    make_job(c, freelancer="")
    tx(c, "cancel_job", "0", sender=CLIENT)
    assert bal(CLIENT) == START and bal(rt.ADDRESS) == 0


def test_cannot_cancel_after_work_is_submitted_even_past_the_deadline(c):
    submitted_job(c)
    advance(WORK_MIN * 5)
    with pytest.raises(Exception, match="no submitted work"):
        tx(c, "cancel_job", "0", sender=CLIENT)
    assert bal(rt.ADDRESS) == ESCROW


def test_only_the_client_can_cancel(c):
    make_job(c)
    advance(WORK_MIN + 1)
    with pytest.raises(Exception, match="Only the client"):
        tx(c, "cancel_job", "0", sender=FREELANCER)


# ================= appeals and the appeal window =================

def test_rejected_work_keeps_funds_locked(c):
    rejected_job(c)
    assert bal(rt.ADDRESS) == ESCROW and bal(FREELANCER) == START
    assert job(c)["escrow"] == "FUNDED"


def test_appeal_can_turn_a_rejection_into_payment(c):
    rejected_job(c)
    tx(c, "appeal", "0", "I did mention coffee", sender=FREELANCER)
    judge(88, 92, reason="appeal accepted")
    assert tx(c, "evaluate", "0", sender=FREELANCER) == "ACCEPTED"
    assert bal(FREELANCER) == START + ESCROW and bal(rt.ADDRESS) == 0


def test_appeal_rules(c):
    submitted_job(c)
    with pytest.raises(Exception, match="Only rejected work"):
        tx(c, "appeal", "0", "please", sender=FREELANCER)
    c2 = module.ProofPayEscrow()
    rejected_job(c2)
    with pytest.raises(Exception, match="Only the freelancer"):
        tx(c2, "appeal", "0", "please", sender=STRANGER)
    tx(c2, "appeal", "0", "please", sender=FREELANCER)
    judge(20, 20)
    tx(c2, "evaluate", "0", sender=FREELANCER)
    with pytest.raises(Exception, match="already appealed"):
        tx(c2, "appeal", "0", "again", sender=FREELANCER)


def test_appeal_is_not_possible_after_the_window_closes(c):
    rejected_job(c)
    advance(APPEAL_MIN + 1)
    with pytest.raises(Exception, match="appeal window has closed"):
        tx(c, "appeal", "0", "too late", sender=FREELANCER)
    assert job(c)["status"] == "REJECTED"


def test_client_cannot_refund_while_an_appeal_is_still_possible(c):
    rejected_job(c)
    advance(APPEAL_MIN - 1)
    with pytest.raises(Exception, match="can still appeal"):
        tx(c, "refund", "0", sender=CLIENT)
    assert bal(rt.ADDRESS) == ESCROW


def test_client_refund_after_the_appeal_window_ends_with_no_appeal(c):
    rejected_job(c)
    advance(APPEAL_MIN + 1)
    tx(c, "refund", "0", sender=CLIENT)
    assert bal(CLIENT) == START and bal(rt.ADDRESS) == 0
    assert job(c)["escrow"] == "REFUNDED"


def test_client_refund_right_after_a_final_rejection(c):
    rejected_job(c)
    tx(c, "appeal", "0", "please recheck", sender=FREELANCER)
    judge(25, 25)
    tx(c, "evaluate", "0", sender=FREELANCER)
    tx(c, "refund", "0", sender=CLIENT)
    assert bal(CLIENT) == START and bal(rt.ADDRESS) == 0


def test_only_the_client_can_claim_a_refund(c):
    rejected_job(c)
    advance(APPEAL_MIN + 1)
    with pytest.raises(Exception, match="Only the client"):
        tx(c, "refund", "0", sender=FREELANCER)


def test_freelancer_can_give_up_and_client_gets_the_money_back(c):
    rejected_job(c)
    tx(c, "concede", "0", sender=FREELANCER)
    assert bal(CLIENT) == START and bal(rt.ADDRESS) == 0
    assert job(c)["escrow"] == "REFUNDED"


def test_concede_only_works_on_rejected_jobs(c):
    submitted_job(c)
    with pytest.raises(Exception, match="Only a rejected job"):
        tx(c, "concede", "0", sender=FREELANCER)


# ================= reputation =================

def test_reputation_for_an_accepted_job(c):
    submitted_job(c)
    judge(90, 80)
    tx(c, "evaluate", "0", sender=CLIENT)
    f, cl = rep(c, FREELANCER), rep(c, CLIENT)
    assert (f["completed"], f["evals"], f["score_sum"], f["earned"]) == (1, 1, 85, ESCROW)
    assert f["rejected"] == 0 and f["appeals_won"] == 0
    assert (cl["jobs"], cl["funded"]) == (1, ESCROW)


def test_reputation_counts_rejections_and_won_appeals(c):
    rejected_job(c)
    assert rep(c, FREELANCER)["rejected"] == 1 and rep(c, FREELANCER)["completed"] == 0
    tx(c, "appeal", "0", "please", sender=FREELANCER)
    judge(95, 95)
    tx(c, "evaluate", "0", sender=FREELANCER)
    f = rep(c, FREELANCER)
    assert f["completed"] == 1 and f["appeals_won"] == 1 and f["evals"] == 2
    assert f["score_sum"] == 25 + 95


def test_reputation_ignores_failed_actions(c):
    submitted_job(c)
    rt.gl.nondet.judge_reply = "broken"
    with pytest.raises(Exception):
        tx(c, "evaluate", "0", sender=CLIENT)
    assert rep(c, FREELANCER)["evals"] == 0


def test_unknown_address_has_an_empty_record_and_lookup_is_case_insensitive(c):
    assert rep(c, STRANGER)["jobs"] == 0 and rep(c, STRANGER)["earned"] == 0
    make_job(c)
    assert rep(c, CLIENT.upper().replace("0X", "0x"))["jobs"] == 1


# ================= timeline =================

def test_timeline_records_every_step_in_order(c):
    make_job(c)
    advance(5)
    tx(c, "submit_work", "0", URL, sender=FREELANCER)
    advance(5)
    judge(90, 90)
    tx(c, "evaluate", "0", sender=CLIENT)
    events = job(c)["events"]
    texts = [e["text"] for e in events]
    assert texts[0].startswith("Job created") and texts[1] == "Work submitted"
    assert texts[2].startswith("Judged 90/100: accepted")
    times = [e["t"] for e in events]
    assert times == sorted(times) and times[1] - times[0] == 300
    assert events[0]["by"] == CLIENT and events[1]["by"] == FREELANCER


def test_timeline_records_refunds_and_appeals(c):
    rejected_job(c)
    tx(c, "appeal", "0", "please", sender=FREELANCER)
    judge(10, 10)
    tx(c, "evaluate", "0", sender=FREELANCER)
    tx(c, "refund", "0", sender=CLIENT)
    texts = [e["text"] for e in job(c)["events"]]
    assert any("appealed" in t for t in texts)
    assert texts[-1].startswith("Refund claimed")


# ================= no double spending =================

def test_nothing_can_move_after_payment_was_released(c):
    submitted_job(c)
    judge(95, 95)
    tx(c, "evaluate", "0", sender=CLIENT)
    after = dict(rt.ledger)
    advance(APPEAL_MIN * 10)
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
    advance(APPEAL_MIN * 10)
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
    judge(10, 10)
    tx(c, "evaluate", "0", sender=CLIENT)
    tx(c, "appeal", "0", "x", sender=FREELANCER)
    judge(95, 95)
    tx(c, "evaluate", "0", sender=CLIENT)
    assert sum(rt.ledger.values()) == total


def test_two_jobs_hold_separate_funds(c):
    make_job(c)
    make_job(c, value=2 * 10**18)
    assert bal(rt.ADDRESS) == ESCROW + 2 * 10**18
    advance(WORK_MIN + 1)
    tx(c, "cancel_job", "1", sender=CLIENT)
    assert bal(rt.ADDRESS) == ESCROW
    assert job(c, "0")["escrow"] == "FUNDED" and job(c, "1")["escrow"] == "REFUNDED"
