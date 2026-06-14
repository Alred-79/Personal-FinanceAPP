"""The net-new what-if LLM tool + the ``proposal`` SSE frame (v6 doc 08).

The tool models a hypothetical, SAVES it as a scenario, evaluates the diff, and
returns a ``scenario_commit`` proposal envelope — nothing is committed until the
returned token is confirmed. ``_whatif_proposal_frame`` turns that envelope into
a ``proposal`` SSE frame; the firewall + propose→confirm token model are
untouched (asserted by the existing security suite, run alongside).
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import server.src.services.assistant_service as svc_mod
from server.src.db.models import (
    Account as AccountORM,
    PlanOfRecord as PlanOfRecordORM,
    Scenario as ScenarioORM,
    User as UserORM,
)
from server.src.services.assistant_service import (
    ActionService,
    _propose_whatif,
    _proposal_frame,
)


def _bind_session(monkeypatch, _engine):
    TestSession = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, future=True
    )
    monkeypatch.setattr(svc_mod, "SessionLocal", TestSession)
    return TestSession


def _user(db_session):
    user = UserORM(username="wf", full_name="WF", email="wf@x.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    db_session.add(
        AccountORM(name="Checking", type="checking", balance=200_000, user_id=user.id)
    )
    db_session.commit()
    return user


def test_propose_whatif_saves_scenario_and_mints_commit_token(
    monkeypatch, db_session, _engine
):
    _bind_session(monkeypatch, _engine)
    user = _user(db_session)

    out = _propose_whatif(
        user.id, monthly_income_change=5000.0, scenario_name="Raise"
    )
    payload = json.loads(out)
    assert payload["kind"] == "proposal"
    assert payload["action"] == "scenario_commit"
    assert payload["confirm_token"]
    assert "ending_balance" in payload["diff"]

    # A real, uncommitted scenario was saved.
    scenario = db_session.execute(select(ScenarioORM)).scalar_one()
    assert payload["scenario_id"] == scenario.id
    # Nothing committed yet — no plan.
    assert db_session.execute(select(PlanOfRecordORM)).scalar_one_or_none() is None

    # The token is a valid scenario_commit token for THIS scenario.
    claims = ActionService.decode_token(payload["confirm_token"])
    assert claims["action"] == "scenario_commit"
    assert claims["params"]["scenario_id"] == scenario.id


def test_propose_whatif_needs_a_concrete_change(monkeypatch, db_session, _engine):
    _bind_session(monkeypatch, _engine)
    user = _user(db_session)
    out = _propose_whatif(user.id)  # no income/expense change
    # Plain guidance text, not a proposal envelope.
    assert "concrete change" in out
    # No scenario saved for an empty what-if.
    assert db_session.execute(select(ScenarioORM)).scalar_one_or_none() is None


def test_whatif_proposal_frame_only_for_proposal_output():
    envelope = json.dumps(
        {
            "kind": "proposal",
            "action": "scenario_commit",
            "scenario_id": 3,
            "summary": "Commit #3",
            "confirm_token": "tok",
            "diff": {"ending_balance": 500.0},
        }
    )
    frame = _proposal_frame({"data": {"output": envelope}})
    assert frame is not None
    assert frame.startswith("event: proposal\n")
    body = json.loads(frame.split("data: ", 1)[1])
    assert body["confirm_token"] == "tok"
    assert body["scenario_id"] == 3

    # Plain text or non-proposal JSON yields no frame.
    assert _proposal_frame({"data": {"output": "ask a concrete question"}}) is None
    assert _proposal_frame({"data": {"output": json.dumps({"kind": "x"})}}) is None


def test_proposal_frame_for_create_rule_has_no_diff():
    """A create_rule proposal yields a ConfirmCard frame with a token and no diff
    (review fix #1 / Pillar 2.0 generic frame path)."""
    envelope = json.dumps(
        {
            "status": "needs_confirmation",
            "kind": "proposal",
            "action": "create_rule",
            "summary": "Create rule 'Payday savings': set aside $50.00 ...",
            "confirm_token": "rule-tok",
        }
    )
    frame = _proposal_frame({"data": {"output": envelope}})
    assert frame is not None
    assert frame.startswith("event: proposal\n")
    body = json.loads(frame.split("data: ", 1)[1])
    assert body["action"] == "create_rule"
    assert body["confirm_token"] == "rule-tok"
    # No diff / scenario_id for a plain rule proposal.
    assert "diff" not in body
    assert "scenario_id" not in body


def test_whatif_token_commits_into_a_real_plan(monkeypatch, db_session, _engine):
    """The minted token confirms end-to-end into a Rule + PlanOfRecord + event."""
    _bind_session(monkeypatch, _engine)
    user = _user(db_session)
    out = _propose_whatif(user.id, monthly_expense_change=200.0, expense_name="Gym")
    claims = ActionService.decode_token(json.loads(out)["confirm_token"])

    # Execute the commit action directly (the confirm endpoint's machinery).
    ActionService.execute(db_session, user.id, claims["action"], claims["params"])
    db_session.flush()
    plan = db_session.execute(select(PlanOfRecordORM)).scalar_one()
    assert plan.scenario_id == claims["params"]["scenario_id"]
