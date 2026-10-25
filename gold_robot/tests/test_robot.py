"""Fail-closed checks for ONE unreleased robot; these DO NOT compile MQL5.

An EA can pass all these checks and still fail economically or with a broker.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EA = (ROOT / 'mt5_robot/QTS_Gold_Robot.mq5').read_text(encoding='utf-8')
PS = (ROOT / 'mt5_robot/Install_QTS_Gold_Robot.ps1').read_text(encoding='utf-8')
BAT = (ROOT / 'INSTALL_ROBOT.bat').read_text(encoding='utf-8')


def body_of(function_name: str) -> str:
    """Select the function body, balancing braces (not a general MQL compiler)."""
    start = EA.find(function_name + '(')
    assert start >= 0, f'{function_name} absent'
    opener = EA.index('{', start)
    nesting = 1
    index = opener + 1
    while nesting and index < len(EA):
        nesting += (EA[index] == '{') - (EA[index] == '}')
        index += 1
    assert nesting == 0
    return EA[opener:index]


def test_demo_only_and_explicit_order_permission():
    assert '#property strict' in EA
    # A pre-release EA needs no compiler Market version. "0.00" caused
    # MetaEditor warning 68, which the fail-closed installer rejected.
    assert not re.search(r'(?m)^\s*#property\s+version\b', EA)

    assert 'ACCOUNT_TRADE_MODE_DEMO' in EA
    assert 'MQLInfoInteger(MQL_TESTER)' in EA
    assert 'if(!DemoOrTester())' in EA
    assert 'if(RealAccountBlocked())' in EA
    assert 'input bool            EnableDemoOrders          = false;' in EA


def test_no_market_entries_or_stop_order_chase():
    entry = body_of('EvaluateNewEntry')
    assert 'request.action=TRADE_ACTION_PENDING;' in entry
    assert 'ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT' in entry
    assert 'OrderSend(request,result)' in entry
    assert 'TRADE_ACTION_DEAL' not in EA
    assert 'ORDER_TYPE_BUY_STOP' not in EA
    assert 'ORDER_TYPE_SELL_STOP' not in EA
    assert 'TRADE_ACTION_MODIFY' not in EA
    assert 'request.price=price;' in entry
    assert 'request.type_filling=ORDER_FILLING_RETURN;' in entry


def test_broker_expiration_required_without_gtc_fallback():
    body = body_of('PendingExpiration')
    assert '(modes&SYMBOL_EXPIRATION_SPECIFIED)==0' in body
    assert 'PendingExpiryBars*frame' in body
    assert 'ServerMidnight()' in body
    assert 'deadline>now+60' in body
    entry = body_of('EvaluateNewEntry')
    assert 'request.type_time=ORDER_TIME_SPECIFIED;' in entry
    assert 'request.expiration=deadline;' in entry
    assert 'ORDER_TIME_GTC' not in EA
    assert 'PendingExpiration(deadline)' in entry


def test_price_structure_uses_only_completed_contiguous_bars():
    body = body_of('PreparePullbackLimit')
    assert 'CopyRates(_Symbol,SignalTimeframe,1,EntrySwingLookbackBars,recent)' in body
    assert 'recent[i].time-recent[i-1].time!=frame' in body
    assert 'low=MathMin(low,recent[i].low)' in body
    assert 'high=MathMax(high,recent[i].high)' in body
    assert 'MathFloor(old_stop/step)' in body
    assert 'MathCeil(old_stop/step)' in body
    assert 'limit' in body.lower()


def test_true_buy_and_sell_limit_do_not_cross_executable_quote():
    body = body_of('PreparePullbackLimit')
    assert 'tick.bid-price<min_pending' in body
    assert 'price-tick.ask<min_pending' in body
    assert 'MaxPendingDistanceAtr*atr' in body
    assert 'LimitEntryBufferAtr' not in EA
    assert 'double old_stop=low-old_stop_buffer;' in body
    assert 'double old_stop=high+old_stop_buffer;' in body
    entry = body_of('EvaluateNewEntry')
    assert 'quote.bid-price<level' in entry
    assert 'price-quote.ask<level' in entry
    assert 'no market entry' in entry.lower()


def test_former_stop_becomes_entry_and_new_stop_stays_behind():
    body = body_of('PreparePullbackLimit')
    assert 'price=NormalizeDouble(MathFloor(old_stop/step)*step,_Digits);' in body
    assert 'price=NormalizeDouble(MathCeil(old_stop/step)*step,_Digits);' in body
    assert 'stop=NormalizeDouble(price-risk_distance,_Digits);' in body
    assert 'stop=NormalizeDouble(price+risk_distance,_Digits);' in body
    assert 'stop>=price' in body
    assert 'stop<=price' in body
    assert 'MinimumStopDistanceAtr' in body
    assert 'MinimumStopSpreadMultiple' in body
    assert 'min_broker+2.0*step' in body
    assert 'risk<minimum_risk' in body
    assert 'risk_ticks=MathCeil(minimum_risk/step-1e-9)' in body
    assert 'minimum_risk=MathMax(atr*MinimumStopDistanceAtr' in body


def test_target_room_is_structural_and_uses_minimum_rr():
    body = body_of('PreparePullbackLimit')
    assert 'high-spread' in body
    assert 'low+spread' in body
    assert 'risk*RewardToRisk' in body
    assert 'return false;' in body


def test_pending_placement_distinguished_from_actual_broker_fill():
    entry = body_of('EvaluateNewEntry')
    assert 'PendingReceipt(sent,code,result.order,result.deal)' in entry
    policy=(ROOT / 'mt5_robot/ExecutionPolicy.mqh').read_text('utf8')
    assert 'code==TRADE_RETCODE_DONE' in policy
    assert 'order>0' in policy
    assert 'if(receipt==QTS_ACCEPTED)' in entry
    assert 'DayKey("PLACEMENTS")' in entry
    assert 'TRADE_RETCODE_DONE_PARTIAL' not in entry
    assert 'result.deal>0' not in entry
    assert 'OnTradeTransaction' in EA
    assert 'TRADE_TRANSACTION_DEAL_ADD' in EA
    assert 'DEAL_COMMISSION' in EA and 'DEAL_SWAP' in EA


def test_broker_history_caps_both_fills_and_pending_attempts():
    assert 'HistorySelect(begin,now)' in EA
    assert 'HistoryDealsTotal()' in EA
    assert 'HistoryOrdersTotal()' in EA
    assert 'OrdersTotal()' in EA
    assert 'MaxPendingOrdersPerDay' in EA
    assert 'MathMax((double)known,stored_pending)' in EA
    assert 'BrokerDailyEntryCount()' in EA
    assert 'MathMax(stored_count,(double)broker_count)' in EA


def test_protective_pending_cancellation_on_pause_kill_and_deinit():
    manage = body_of('ManageOwnedPendingOrders')
    for term in ('EmergencyFlattenOwned', 'PauseNewEntries', '!EnableDemoOrders',
                 'breached', 'BrokerSessionAllowed()', 'trader.OrderDelete(ticket)',
                 'ORDER_MAGIC', 'ORDER_SYMBOL', 'ORDER_TIME_EXPIRATION',
                 'LatchExecutionHalt('):
        assert term in manage, term
    assert 'ManageOwnedPendingOrders(true);' in body_of('OnDeinit')
    assert 'ManageOwnedPendingOrders();' in body_of('OnTick')
    assert 'ManageOwnedPendingOrders();' in body_of('OnTimer')


def test_one_position_or_order_with_atomic_entry_lease():
    assert 'AnyConflictingPositionOrOrder()' in body_of('EvaluateNewEntry')
    consider = body_of('ConsiderNewEntry')
    assert 'AcquireEntryMutex(token)' in consider
    assert 'ReleaseEntryMutex(token)' in consider
    assert 'GlobalVariableSetOnCondition' in EA


def test_risk_budget_uses_broker_contract_facts_no_roundup():
    size = body_of('SizedLots')
    for term in ('OrderCalcMargin(', 'SYMBOL_VOLUME_MIN',
                 'SYMBOL_VOLUME_MAX', 'SYMBOL_VOLUME_STEP',
                 'MathFloor(budget/(one_lot_cost*step)', 'if(volume<minimum',
                 'MaxMarginUsePct', 'EstimatedMonetaryLoss('):
        assert term in size, term
    monetary = body_of('EstimatedMonetaryLoss')
    for term in ('OrderCalcProfit(', 'AssumedRoundTurnFeePerLot*volume',
                 'AdverseStopSlipPrice', 'stressed_stop'):
        assert term in monetary, term
    assert 'RiskPerTradePct' in EA
    assert 'MaxDailyLossPct' in EA
    assert 'MaxPeakDrawdownPct' in EA


def test_broker_preflight_and_no_ambiguous_retries():
    entry = body_of('EvaluateNewEntry')
    assert EA.count('OrderSend(request,result)') == 1
    assert 'OrderCheck(request,check)' in entry
    assert 'check.retcode!=0' in entry
    assert entry.index('OrderCheck(request,check)') < entry.index('OrderSend(request,result)')
    assert 'LatchExecutionHalt("ambiguous pending submission")' in entry
    assert 'AccountKey("EXEC_HALT")' in EA


def test_entry_signal_is_closed_bar_causal_and_gated():
    assert 'CopyBuffer(fast_handle,0,1,2,fast)' in EA
    assert 'CopyBuffer(slow_handle,0,1,2,slow)' in EA
    assert 'CopyRates(_Symbol,SignalTimeframe,0,3,bars)' in EA
    assert 'bars[1].time-bars[0].time!=frame' in EA
    assert 'h1_running-h1_previous!=3600' in EA
    assert 'last_closed_bar=closed;' in EA
    assert 'MaxSpreadBps' in EA and 'MaxTickAgeSeconds' in EA
    assert 'SYMBOL_ORDER_LIMIT' in EA


def test_no_network_or_self_expanding_position_size():
    for forbidden in ('WebRequest(', 'ShellExecute(', '#import', 'WinExec(',
                      'TerminalClose(', 'FileDelete(', 'Martingale', 'DoubleLots',
                      'TRADE_ACTION_DEAL', 'ORDER_TIME_GTC'):
        assert forbidden not in EA, forbidden


def test_only_owned_positions_are_closed_and_logged():
    body = body_of('ManageOwnedPositions')
    assert 'PositionGetInteger(POSITION_MAGIC)!=RobotMagic' in body
    assert 'trader.PositionClose(ticket)' in body
    assert 'PositionGetDouble(POSITION_TP)' in body
    assert 'PositionGetDouble(POSITION_SL)' in body
    assert 'DEAL_FEE' in EA
    assert 'GetTickCount64()-started' in EA


def test_source_braces_parentheses_and_brackets_coarsely_balance():
    for opening, closing in (('(', ')'), ('{', '}'), ('[', ']')):
        assert EA.count(opening) == EA.count(closing)
    assert EA.endswith('//+------------------------------------------------------------------+\n')


def test_installer_only_deploys_after_compiler_and_supports_rollback():
    for snippet in ('Get-FileHash', 'SHA256', 'Start-Process', 'MetaEditor',
                    'Test-Path -LiteralPath $compiled -PathType Leaf',
                    'Remove-Item -LiteralPath $compiled -Force',
                    'if (-not $completed)', 'Copy-Item -LiteralPath $backupEX5',
                    'Copy-Item -LiteralPath $backupSource', '\\s+errors?',
                    '\\s+warnings?', 'throw', 'finally'):
        assert snippet in PS, snippet
    assert '-ExecutionPolicy Bypass' in BAT
    for forbidden in ('order_send', 'MT5_PASSWORD', 'QTS_MT5_LOGIN'):
        assert forbidden not in PS and forbidden not in BAT


def test_release_is_explicitly_unvalidated_and_observe_only_by_default():
    import json
    release = json.loads((ROOT / 'docs/RELEASE_STATUS.json').read_text('utf-8'))
    assert release['version'] == '0.0.0-development'
    assert release['release_state'] == 'NOT_RELEASED'
    assert release['default_order_permission'] is False
    assert release['market_entry_orders_permitted'] is False
    assert release['real_money_orders_permitted'] is False
    assert isinstance(release['testing']['metaeditor_compiled_ex5'], bool)
    if release['testing']['metaeditor_compiled_ex5']:
        log=(ROOT / 'evidence/compile.log').read_text(encoding='utf-16')
        assert 'Result: 0 errors, 0 warnings' in log
    else:
        assert 'metaeditor' in release['testing']['reason'].lower() or 'native mql5 compile' in release['testing']['reason'].lower()
    assert release['testing']['validated_profitable_edge'] is False


def test_owner_relocation_math_long_and_short_examples():
    """Numeric examples pin the SAME old-stop calculation as new entry.

    This independently mirrors the intended arithmetic; it is not a broker
    fill backtest or a substitute for MetaEditor execution.
    """
    import math

    def levels(side, low, high, atr, spread, tick, stops_level, point):
        old_buffer = max(atr * 0.20, spread * 1.2)
        broker_min = (stops_level + 2) * point
        safe_gap = max(atr * 0.25, spread * 3.0, broker_min + 2 * tick)
        gap = math.ceil(safe_gap / tick - 1e-9) * tick
        if side == 'BUY':
            old_stop = math.floor((low - old_buffer) / tick) * tick
            new_entry = math.floor((low - old_buffer) / tick) * tick
            new_stop = round(new_entry - gap, 2)
            assert new_entry == old_stop
            assert new_stop < new_entry < low
        else:
            old_stop = math.ceil((high + old_buffer) / tick) * tick
            new_entry = math.ceil((high + old_buffer) / tick) * tick
            new_stop = round(new_entry + gap, 2)
            assert new_entry == old_stop
            assert high < new_entry < new_stop
        assert abs(new_stop - new_entry) + 1e-6 >= max(atr * 0.25, spread * 3.0, broker_min)
        return round(new_entry, 2), round(new_stop, 2)

    assert levels('BUY', 3000.0, 3030.0, 8.0, .2, .01, 30, .01) == (2998.4, 2996.4)
    assert levels('SELL', 3000.0, 3030.0, 8.0, .2, .01, 30, .01) == (3031.6, 3033.6)
    assert levels('BUY', 3000.0, 3030.0, 1.0, .3, .01, 70, .01)[1] < 2999


def test_one_canonical_initial_development_release():
    import json
    assert 'PRO 3' not in EA
    assert 'PRO 3' not in PS
    assert 'PRO 3' not in BAT
    assert 'initial development' in (ROOT / 'README.txt').read_text(encoding='utf-8').lower()
    release = json.loads((ROOT / 'docs/RELEASE_STATUS.json').read_text(encoding='utf-8'))
    assert release['release_state'] == 'NOT_RELEASED'
    assert 'old-stop limit' in release['entry_policy'].lower() and 'retest limit' in release['entry_policy'].lower()


def test_atomic_mutex_first_creation_cannot_overwrite_winner():
    acquire = body_of('AcquireEntryMutex')
    assert 'GlobalVariableTemp(key)' in acquire
    assert 'GlobalVariableSet(key, 0.0)' not in acquire
    assert 'GlobalVariableSetOnCondition(key, token, 0.0)' in acquire
    assert 'GlobalVariableSetOnCondition(key, token, active)' in acquire
    assert 'token > active+300.0' in acquire


def test_equity_peak_is_updated_monotonically_using_cas():
    risk = body_of('RiskState')
    assert 'GlobalVariableSetOnCondition(peak_key, equity, peak)' in risk
    assert 'GlobalVariableSet(peak_key, equity)' not in risk
    assert 'GlobalVariableGet(peak_key, peak)' in risk
    assert 'peak<equity' in risk
    assert 'Concurrent equity peak update unresolved' in risk


def test_broker_rejected_and_partial_closes_are_both_execution_incidents():
    manage = body_of('ManageOwnedPositions')
    assert 'trader.ResultRetcode()' in manage
    assert 'code==TRADE_RETCODE_DONE_PARTIAL' in manage
    assert 'ProtectiveRequestDue(ticket,"CLOSE")' in manage
    assert 'PositionSelectByTicket(ticket)' in manage
    assert 'cache convergence is asynchronous' in manage
    assert 'protective close failed or broker outcome unknown' in manage


def test_cancelled_pending_must_disappear_from_terminal_book():
    manage = body_of('ManageOwnedPendingOrders')
    assert 'ret!=TRADE_RETCODE_DONE' in manage
    assert 'else if(OrderSelect(ticket))' in manage
    assert 'ProtectiveRequestDue(ticket,"CANCEL")' in manage
    assert 'state==ORDER_STATE_FILLED' in manage


def test_durability_failure_cancels_accepted_order_and_blocks_new_entries():
    entry = body_of('EvaluateNewEntry')
    assert entry.index('LatchExecutionHalt("pending placement counter not durable")') < entry.index('trader.OrderDelete(result.order)')
    assert 'trader.ResultRetcode()!=TRADE_RETCODE_DONE' in entry
    assert 'return;' in entry


def test_protective_timer_is_a_mandatory_startup_gate():
    startup = body_of('OnInit')
    assert 'if(!EventSetTimer(10))' in startup
    timer_index = startup.index('if(!EventSetTimer(10))')
    assert 'return INIT_FAILED;' in startup[timer_index:timer_index + 550]


def test_deal_audit_uses_actual_broker_receipts_and_deduplicates_charts():
    logging = body_of('AppendBrokerDealAudit')
    assert 'GlobalVariableTemp(receipt)' not in logging
    assert 'FileIsEnding(file)' in logging
    assert 'fields[6]==deal_key' in logging
    assert 'fields[3]==login_key' in logging
    assert 'fields[2]==broker' in logging
    assert 'fields[5]==magic_key' in logging
    assert 'FILE_SHARE_WRITE' not in logging.split('int flags=', 1)[1].split(';', 1)[0]
    assert 'FILE_COMMON|FILE_READ|FILE_WRITE|FILE_CSV' in logging
    assert 'FILE_SHARE_READ' in logging
    assert 'FileSeek(file,0,SEEK_END)' in logging
    assert 'FileFlush(file)' in logging
    assert 'FileClose(file)' in logging
    assert 'FileWrite(file,broker_time_msc' in logging
    assert 'AccountInfoString(ACCOUNT_SERVER)' in logging
    assert 'DoubleToString(provisional_net,8)' in logging
    trans = body_of('OnTradeTransaction')
    for field in ('DEAL_TIME_MSC','DEAL_PROFIT','DEAL_COMMISSION','DEAL_SWAP','DEAL_FEE'):
        assert field in trans
    assert 'LatchExecutionHalt("broker transaction ledger could not be appended")' in trans
    assert 'LatchExecutionHalt("broker deal event could not be read from history")' in trans
    assert 'DEAL_SYMBOL)!=_Symbol' in trans


def test_unchanged_previous_structural_stop_is_the_entry_not_market():
    preparation = body_of('PreparePullbackLimit')
    assert 'double old_stop=low-old_stop_buffer;' in preparation
    assert 'price=NormalizeDouble(MathFloor(old_stop/step)*step,_Digits);' in preparation
    assert 'double old_stop=high+old_stop_buffer;' in preparation
    assert 'price=NormalizeDouble(MathCeil(old_stop/step)*step,_Digits);' in preparation
    assert 'risk_distance=risk_ticks*step' in preparation
    assert 'tick.bid-price<min_pending' in preparation
    assert 'price-tick.ask<min_pending' in preparation
    assert 'risk*RewardToRisk' in preparation
    assert 'TRADE_ACTION_DEAL' not in body_of('EvaluateNewEntry')


def test_daily_loss_is_durably_latched_instead_of_rearming_after_recovery():
    risk = body_of('RiskState')
    assert 'DayKey("DAILY_STOP")' in risk
    assert 'AccountKey("DRAWDOWN_STOP")' in risk
    assert 'GlobalVariableSet(daily_stop,1.0)' in risk
    assert 'GlobalVariableSet(peak_stop,1.0)' in risk
    assert 'GlobalVariablesFlush()' in risk
    assert 'daily_latched>0.0 || peak_latched>0.0' in risk
    assert 'breached=daily_now || drawdown_now' in risk
    assert 'GlobalVariableSet(daily_stop,0.0)' not in EA
    assert 'GlobalVariableSet(peak_stop,0.0)' not in EA


def test_pending_order_is_cancelled_when_another_position_appears():
    conflict = body_of('AnySameSymbolPosition')
    assert 'PositionGetTicket(i)' in conflict
    assert 'PositionGetString(POSITION_SYMBOL)==_Symbol' in conflict
    cancel = body_of('ManageOwnedPendingOrders')
    assert 'AnySameSymbolPosition()' in cancel
    assert 'trader.OrderDelete(ticket)' in cancel


def test_ledger_dedup_persists_across_restart_and_rejects_truncated_rows():
    ledger = body_of('AppendBrokerDealAudit')
    assert 'for(int i=0;i<15;i++)' in ledger
    assert 'truncated historical CSV row' in ledger
    assert 'FileClose(file);' in ledger
    assert 'return true; // Durable existing record' in ledger
    assert 'FileSeek(file,0,SEEK_END)' in ledger
    assert 'FileWrite(file,broker_time_msc,' in ledger
    assert 'written==0' in ledger


def test_first_risk_key_creation_is_serialized_across_charts():
    initializer = body_of('AcquireStateInitMutex')
    reader = body_of('ReadNumber')
    assert 'AccountKey("STATE_INIT_LOCK")' in initializer
    assert 'GlobalVariableTemp(key)' in initializer
    assert 'GlobalVariableSetOnCondition(key,token,0.0)' in initializer
    assert 'GlobalVariableSetOnCondition(key,token,current)' in initializer
    assert 'AcquireStateInitMutex(token)' in reader
    assert 'ReleaseStateInitMutex(token)' in reader
    assert reader.index('AcquireStateInitMutex(token)') < reader.index('GlobalVariableSet(key,seed)')
    assert reader.index('GlobalVariableSet(key,seed)') < reader.index('ReleaseStateInitMutex(token)')


def test_compiler_warning_68_does_not_recur_and_warnings_remain_fatal():
    """Regression: clean MetaEditor result + fresh EX5 beats anomalous exit 1."""
    assert not re.search(r'(?m)^\s*#property\s+version\b', EA)
    assert '[regex]::Matches($logText' in PS
    assert r'Result:\s*(\d+)\s+errors?\s*,\s*(\d+)\s+warnings?' in PS
    assert '$summaries.Count -ne 1' in PS
    assert '$errorsCount -ne 0 -or $warningsCount -ne 0' in PS
    assert 'Test-Path -LiteralPath $compiled -PathType Leaf' in PS
    assert '$binary.LastWriteTimeUtc -lt $compileStartedUtc.AddSeconds(-2)' in PS
    assert '(Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash -ne $actualHash' in PS
    assert '$proc.ExitCode -ne 0 -and $proc.ExitCode -ne 1' in PS
    assert '$proc.ExitCode -eq 1' in PS
    assert PS.index('$errorsCount -ne 0 -or $warningsCount -ne 0') < PS.index('$proc.ExitCode -eq 1')
    assert PS.index('Test-Path -LiteralPath $compiled -PathType Leaf') < PS.index('$proc.ExitCode -eq 1')
    assert 'if (-not $completed)' in PS
    assert r"if ($sourceText -match '(?im)^\s*#property\s+version\b')" in PS
    assert 'SOURCE_CHECKSUMS.json' in PS
    assert 'Get-FileHash -LiteralPath $source -Algorithm SHA256' in PS


def test_installer_compilation_requires_current_built_binary():
    """No optimistic exit-code workaround may disable the artifact checks."""
    for required in (
        'Remove-Item -LiteralPath $compiled -Force',
        'Remove-Item -LiteralPath $log -Force',
        '$binary.Length -lt 1000',
        '$binary.LastWriteTimeUtc',
        '$summaries.Count -ne 1',
        '$completed = $true',
        'if (-not $completed)',
    ):
        assert required in PS
    assert PS.index('Remove-Item -LiteralPath $compiled -Force') < PS.index('$proc = Start-Process')
    assert PS.index('$summaries.Count -ne 1') < PS.index('$completed = $true')
    assert PS.index('$proc.ExitCode -eq 1') < PS.index('$completed = $true')


def test_package_source_checksums_match_files():
    """No edited MQ5, installer or operator documentation has a stale digest."""
    import hashlib
    import json

    manifest = json.loads((ROOT / 'docs/SOURCE_CHECKSUMS.json').read_text('utf-8'))
    for row in manifest['sha256_files']:
        data = (ROOT / row['path']).read_bytes()
        assert row['bytes'] == len(data), row['path']
        assert row['sha256'] == hashlib.sha256(data).hexdigest(), row['path']


def test_unresolved_send_marker_precedes_submit_and_blocks_restart():
    entry=body_of('EvaluateNewEntry')
    marker='GlobalVariableSet(AccountKey("SUBMIT_INTENT"),(double)TimeTradeServer())'
    assert entry.index(marker)<entry.index('OrderSend(request,result)')
    assert 'AccountKey("SUBMIT_INTENT")' in body_of('NewTradesAllowedByRisk')
    assert 'GlobalVariablesFlush()' in body_of('LatchExecutionHalt')


def test_unvalidated_edge_cannot_be_armed_on_demo_by_input():
    assert 'StrategyEvidenceApproved()' in body_of('ConsiderNewEntry')
    gate=body_of('StrategyEvidenceApproved')
    assert 'return MQLInfoInteger(MQL_TESTER)!=0;' in gate
    assert 'EnableDemoOrders' not in gate


def test_tester_receipts_do_not_deduplicate_against_broker_deals():
    assert 'flags &= ~FILE_COMMON' in body_of('AppendBrokerDealAudit')
    assert 'QTS_tester_deals_' in body_of('OnInit')


def test_restart_baseline_accounts_for_already_realized_daily_losses():
    risk=body_of('RiskState')
    assert 'AccountInfoDouble(ACCOUNT_BALANCE)-day_changes' in risk
    assert 'HistorySelect(ServerMidnight(),TimeTradeServer())' in risk
    assert 'MathMax(equity,' in risk


def test_two_percent_risk_is_a_ceiling_not_the_default():
    assert 'RiskPerTradePct>2.0' in EA
    assert 'input double          RiskPerTradePct           = 1.0;' in EA
    assert 'RiskPerTradePct>2.0' in EA and 'RiskPerTradePct>1.0' not in EA
    assert 'return MQLInfoInteger(MQL_TESTER)!=0;' in EA


def test_intraday_retest_is_research_candidate_not_forced_trade():
    assert 'SignalTimeframe!=PERIOD_M5' in EA
    entry = body_of('EvaluateNewEntry')
    assert 'EntryStyle==QTS_RETEST_LIMIT ? PrepareRetestLimit' in entry
    assert 'PreparePullbackLimit' in entry
    assert 'MQLInfoInteger(MQL_TESTER)!=0' in body_of('StrategyEvidenceApproved')
    retest = body_of('PrepareRetestLimit')
    for term in ('CopyRates(_Symbol,SignalTimeframe,1,EntrySwingLookbackBars,recent)',
                 'recent[i].time-recent[i-1].time!=frame',
                 'SYMBOL_TRADE_STOPS_LEVEL', 'RetestDepthAtr', 'target>high-spread',
                 'target<low+spread', 'RewardToRisk*risk'):
        assert term in retest, term

def test_small_account_risk_guards_and_fee_budget():
    size = body_of('SizedLots')
    assert 'volume<minimum' in size
    assert 'loss>budget+1e-8' in size
    assert 'RiskPerTradePct>2.0' in EA
    assert 'MaxDailyLossPct           = 3.0;' in EA
    assert 'MaxTradesPerDay           = 8;' in EA
    assert 'MaxPendingOrdersPerDay    = 20;' in EA
    assert 'AssumedRoundTurnFeePerLot<0.0' in EA
    assert 'AdverseStopSlipPrice<0.0' in EA
