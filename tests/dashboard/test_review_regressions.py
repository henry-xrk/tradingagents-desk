import math
from decimal import ROUND_HALF_UP, Decimal

import pytest
from pydantic import ValidationError

from backend.schemas.models import PositionSizeRequest
from backend.services.trade_plan import PositionInputs, calculate_position, parse_labeled_price


def size(**changes):
    args = {
        "entry_price": 100,
        "stop_loss": 90,
        "action": "Buy",
        "available_capital": 1000,
        "available_cash": 1000,
        "max_risk_amount": 100,
        "max_position_percent": 100,
    }
    args.update(changes)
    return calculate_position(PositionInputs(**args))

def test_ladder_budget_regression():
    p=size(scale_in_prices=[200,180])
    assert p['shares']==0 # First share alone risks 110, above the 100 cap.
    assert p['capital_used']==0

@pytest.mark.parametrize('prices',[[100,98],[200,180],[91,95,107],[133,99,92]])
@pytest.mark.parametrize('cost_bps',[0,25,100])
def test_actual_orders_obey_all_caps(prices,cost_bps):
    p=size(scale_in_prices=prices,cost_bps=cost_bps)
    rows=p['limit_entries']
    cash=sum(x['shares']*x['price']*(1+cost_bps/10000) for x in rows)
    loss=sum(x['shares']*(x['price']-90+x['price']*cost_bps/10000) for x in rows)
    assert cash<=1000+1e-8 and loss<=100+1e-8
    rate=Decimal(cost_bps)/10000
    exact_cash=sum(Decimal(str(x['price']))*x['shares']*(1+rate) for x in rows)
    exact_loss=sum((Decimal(str(x['price']))-90+Decimal(str(x['price']))*rate)*x['shares'] for x in rows)
    assert p['capital_used']==float(exact_cash.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))
    assert p['planned_loss']==float(exact_loss.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))

@pytest.mark.parametrize('action',['Sell','Hold','BUY NOW',None])
def test_no_new_positions_for_ambiguous_or_sell_actions(action):
    assert size(action=action)['status']=='unavailable'

def test_stop_must_be_below_every_buy_level():
    assert size(scale_in_prices=[100,85])['status']=='unavailable'
    assert size(stop_loss=110)['status']=='unavailable'

@pytest.mark.parametrize('value',['nan','inf','1e999'])
def test_reject_nonfinite_model_prices(value):
    assert parse_labeled_price('**Entry Price**: '+value,'Entry Price') is None

@pytest.mark.parametrize('field',['entry_price','stop_loss','max_risk_amount','available_cash','cost_bps'])
def test_request_rejects_nonfinite(field):
    with pytest.raises(ValidationError):
        PositionSizeRequest(**{field:math.inf})


def test_subscription_sharing_limit_is_classified():
    from backend.errors import classify_exception
    code, message = classify_exception(RuntimeError(
        "The ChatGPT user has reached their Subscription Sharing usage limit."
    ))
    assert code == "quota"
    assert "usage limit" in message or "quota" in message
