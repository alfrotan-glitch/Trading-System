//+------------------------------------------------------------------+
//| QTS Gold Robot — INITIAL DEVELOPMENT, former-stop limit entry          |
//| DEMO-only; economic edge UNVALIDATED; never trade a LIVE account |
//| Capital preservation takes precedence over signal frequency.    |
//+------------------------------------------------------------------+
#property copyright "QTS Trading System"
// Pre-release metadata: no public Market version declared.
#property strict
#property description "QTS Gold Robot: initial development, LIMIT entry at former stop-invalidation level."
#property description "Strategy is UNVALIDATED and may lose money. LIVE account orders are blocked."

#include <Trade\Trade.mqh>
#include "ExecutionPolicy.mqh"

// All input defaults are conservative *engineering* choices, NOT optimized alpha.
input bool            EnableDemoOrders          = false; // OFF by default.
input bool            EnableDemoForwardOrders    = false; // Independent authorization, connected WMMarkets DEMO only.
input double          DemoForwardRiskCapPct      = 0.25; // DEMO hard cap; never weakens trade-level risk.
input bool            EnableEntryDiagnostics    = true; // Closed-bar diagnostic reasons in Tester and connected DEMO Experts logs.
input bool            PauseNewEntries           = false;
input bool            EmergencyFlattenOwned     = false; // Emergency CLOSE of THIS magic only.
enum QTS_ENTRY_STYLE { QTS_FORMER_STOP_LIMIT=0, QTS_RETEST_LIMIT=1, QTS_BREAK_ACCEPT_RETEST=2, QTS_SWEEP_RECLAIM=3, QTS_TREND_IMPULSE=4, QTS_RANGE_REJECTION=5, QTS_INSIDE_BREAKOUT=6 };
input QTS_ENTRY_STYLE EntryStyle               = QTS_FORMER_STOP_LIMIT;
input ENUM_TIMEFRAMES SignalTimeframe           = PERIOD_M15;
input int             FastEmaPeriod             = 20;
input int             SlowEmaPeriod             = 50;
input int             AtrPeriod                 = 14;
input int             AdxPeriod                 = 14;
input double          MinimumAdx                = 20.0;
input double          RewardToRisk              = 1.0; // Unvalidated research setting; not a profitability claim.
input double          RiskPerTradePct           = 1.0; // Up to 2%, NEVER a mandatory 2% risk.
input double          MaxDailyLossPct           = 3.0;
input double          MaxPeakDrawdownPct        = 8.0;
input bool            TesterIgnoreDailyAndPeakStops = true; // ONLY Strategy Tester: observe all opportunities.
input bool            FlattenOnEquityBreach     = true;
input int             MaxTradesPerDay           = 8;
input int             MaxSpreadPoints           = 90;
input double          MaxSpreadBps              = 3.0;
input double          MaxSpreadVsAtrPct         = 20.0;
input int             MaxTickAgeSeconds         = 5;
input int             MaxPositionMinutes        = 180;
input double          MaxMarginUsePct           = 20.0;
input int             BrokerStartHour           = 6;    // Broker server time.
input int             BrokerEndHour             = 22;   // Exclusive.
input int             RolloverBlackoutMin       = 30;   // No new orders near midnight.
input ulong           RobotMagic                = 6241024;
input int             MaxDeviationPoints        = 30;
input bool            EnableH1TrendFilter       = true;
input bool            ResetExecutionHalt        = false; // Only after manual broker reconciliation.
// Entry = the OLD structural stop (beyond the recent swing).
// New protective SL is farther outside, at the minimum safe broker/volatility gap.
// This is a deep LIMIT fade, not evidence of higher win probability.
input int             EntrySwingLookbackBars     = 8;    // Closed bars only.
input double          StructuralStopBufferAtr   = 0.20; // Where the OLD SL would sit beyond swing.
input double          MinimumStopDistanceAtr    = 0.25; // NEW SL gap after shifted entry; volatility floor.
input double          MinimumStopSpreadMultiple = 3.0;  // Avoid spread-sized micro-stops.
input double          MaxPendingDistanceAtr     = 1.80; // Do not chase far-away entry zones.
input int             PendingExpiryBars         = 2;    // Server-managed order expiration.
input int             MaxPendingOrdersPerDay    = 20; // Attempts; cannot force fills.
input double          RetestDepthAtr            = 0.35; // Research retest; may increase fill rates, not edge.
input double          StructureBreakConfirmAtr  = 0.07;
input double          StructureRetestWindowAtr  = 0.35;
input double          StructureEntryOffsetAtr   = 0.04;
input double          AssumedRoundTurnFeePerLot = 10.0; // USD per 1.0 lot (unverified broker tariff).
input double          AdverseStopSlipPrice      = 0.10; // XAUUSD price units, not a fill guarantee.
input double          MinimumTargetFeeMultiple  = 2.0;  // Gross TP profit must cover >= 2x assumed total fees.


CTrade trader;
int fast_handle = INVALID_HANDLE;
int slow_handle = INVALID_HANDLE;
int atr_handle = INVALID_HANDLE;
int adx_handle = INVALID_HANDLE;
int h1_handle = INVALID_HANDLE;
datetime last_closed_bar = 0;
string status_text = "Initialization";
bool local_execution_halt = false;
string audit_file="QTS_Gold_Robot_Broker_Deals.csv";
bool broker_was_connected=false;

// Broker DEMO forwarding is a separately authorized experiment with virtual funds.
// No result permits REAL account orders. This is NOT economic edge validation.
bool ConnectedDemoForwardAuthorized()
  {
   if(MQLInfoInteger(MQL_TESTER)!=0 || !EnableDemoOrders ||
      !EnableDemoForwardOrders ||
      AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO)
      return false;
   return _Symbol=="XAUUSD@" &&
          StringFind(AccountInfoString(ACCOUNT_SERVER),"WMMarkets")==0 &&
          AccountInfoString(ACCOUNT_CURRENCY)=="USD";
  }

bool StrategyEvidenceApproved()
  {
   return MQLInfoInteger(MQL_TESTER)!=0 || ConnectedDemoForwardAuthorized();
  }

double EffectiveTradeRiskPct()
  {
   if(MQLInfoInteger(MQL_TESTER)!=0)
      return RiskPerTradePct;
   if(!ConnectedDemoForwardAuthorized())
      return 0.0;
   return MathMin(RiskPerTradePct,DemoForwardRiskCapPct);
  }

// This bypass is strictly limited to simulated Strategy Tester sessions.
// It never disables per-order stops, lot/margin, broker checks, or incident halts.
bool TesterResearchNoDailyStops()
  {
   return MQLInfoInteger(MQL_TESTER)!=0 && TesterIgnoreDailyAndPeakStops;
  }

// ------------------------------------------------------------------
// Authority and account identity. Never submit real capital orders.
// ------------------------------------------------------------------
bool DemoOrTester()
  {
   if(MQLInfoInteger(MQL_TESTER) != 0)
      return true; // All Strategy Tester orders are simulated.
   return AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO;
  }

bool RealAccountBlocked()
  {
   return (MQLInfoInteger(MQL_TESTER) == 0 &&
           AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO);
  }

string AccountKey(const string part)
  {
   // Terminal global-variable names <=63 chars, account-scoped and magic-scoped.
   return StringFormat("QTS2_%I64d_%I64u_%s", AccountInfoInteger(ACCOUNT_LOGIN), RobotMagic, part);
  }

datetime ServerMidnight()
  {
   datetime now = TimeTradeServer();
   if(now <= 0)
      return 0;
   MqlDateTime dt;
   if(!TimeToStruct(now, dt))
      return 0;
   dt.hour=0;
   dt.min=0;
   dt.sec=0;
   return StructToTime(dt);
  }

string DayKey(const string part)
  {
   MqlDateTime dt;
   if(!TimeToStruct(TimeTradeServer(), dt))
      return "";
   return AccountKey(StringFormat("%s_%04d%02d%02d", part,dt.year,dt.mon,dt.day));
  }

// A separate short-lived initialization mutex serializes FIRST CREATION
// of persistent risk keys. The entry-order mutex must NOT be reused here:
// risk checks run while the entry-order mutex is already held.
bool AcquireStateInitMutex(double &token)
  {
   token=0.0;
   string key=AccountKey("STATE_INIT_LOCK");
   if(!GlobalVariableCheck(key) &&
      !GlobalVariableTemp(key) && !GlobalVariableCheck(key))
      return false;
   datetime now=TimeTradeServer();
   if(now<=0)
      return false;
   double current=0.0;
   if(!GlobalVariableGet(key,current))
      return false;
   token=(double)now;
   if(current==0.0)
      return GlobalVariableSetOnCondition(key,token,0.0);
   if(current>0.0 && token>current+300.0)
      return GlobalVariableSetOnCondition(key,token,current);
   return false;
  }

void ReleaseStateInitMutex(const double token)
  {
   if(token<=0.0)
      return;
   if(!GlobalVariableSetOnCondition(AccountKey("STATE_INIT_LOCK"),0.0,token))
      Print("QTS WARNING: state initialization lock release mismatch");
  }

bool ReadNumber(const string key, const double seed, double &value)
  {
   if(key=="" || !MathIsValidNumber(seed) || seed<0.0)
      return false;
   if(!GlobalVariableCheck(key))
     {
      double token=0.0;
      if(!AcquireStateInitMutex(token))
         return false; // Never seed a risk key concurrently with another EA.
      bool initialized=GlobalVariableCheck(key);
      if(!initialized)
         initialized=GlobalVariableSet(key,seed)!=0;
      if(initialized) GlobalVariablesFlush();
      ReleaseStateInitMutex(token);
      if(!initialized)
         return false;
     }
   if(!GlobalVariableGet(key,value))
      return false;
   return MathIsValidNumber(value) && value>=0.0;
  }

bool RiskState(const double equity, bool &breached)
  {
   breached = false;
   if(equity <= 0.0 || !MathIsValidNumber(equity))
     {
      status_text = "No valid account equity";
      return false;
     }
   string day_key = DayKey("START");
   string peak_key = AccountKey("PEAK");
   double day_equity = 0.0, peak = 0.0;
   double day_seed=equity;
   if(!GlobalVariableCheck(day_key))
     {
      // First start after midnight must not erase already realized losses.
      // Historical midnight floating PnL is unavailable; use the more
      // conservative of reconstructed starting balance and current equity.
      if(!HistorySelect(ServerMidnight(),TimeTradeServer()))
         return false;
      double day_changes=0.0;
      for(int i=0;i<HistoryDealsTotal();i++)
        {
         ulong deal=HistoryDealGetTicket(i);
         if(deal==0) return false;
         day_changes+=HistoryDealGetDouble(deal,DEAL_PROFIT)+
                      HistoryDealGetDouble(deal,DEAL_COMMISSION)+
                      HistoryDealGetDouble(deal,DEAL_SWAP)+
                      HistoryDealGetDouble(deal,DEAL_FEE);
        }
      day_seed=MathMax(equity,AccountInfoDouble(ACCOUNT_BALANCE)-day_changes);
     }
   if(!ReadNumber(day_key, day_seed, day_equity) ||
      !ReadNumber(peak_key, equity, peak))
     {
      status_text = "Risk state unreadable - no orders";
      return false;
     }
   if(equity > peak)
     {
      // Another chart can update this account's peak concurrently. CAS
      // prevents a slower writer from lowering the already recorded peak.
      if(GlobalVariableSetOnCondition(peak_key, equity, peak))
        {
         peak = equity;
         GlobalVariablesFlush();
        }
      else
        {
         if(!GlobalVariableGet(peak_key, peak) ||
            !MathIsValidNumber(peak) || peak<equity)
           {
            status_text = "Concurrent equity peak update unresolved";
            return false;
           }
        }
     }
   if(day_equity <= 0.0 || peak <= 0.0)
     {
      status_text = "Invalid risk baseline";
      return false;
     }
   if(TesterResearchNoDailyStops())
     {
      // Observe later opportunities after losses in TESTER ONLY.
      breached=false;
      return true;
     }
   // Breaches are durable stops. A recovery in equity MUST NOT silently
   // re-enable new entries after the daily loss threshold was crossed.
   string daily_stop=DayKey("DAILY_STOP");
   string peak_stop=AccountKey("DRAWDOWN_STOP");
   double daily_latched=0.0, peak_latched=0.0;
   if(!ReadNumber(daily_stop,0.0,daily_latched) ||
      !ReadNumber(peak_stop,0.0,peak_latched))
     {
      status_text="Persistent risk halt unavailable";
      return false;
     }
   bool daily_now=equity<=day_equity*(1.0-MaxDailyLossPct/100.0);
   bool drawdown_now=equity<=peak*(1.0-MaxPeakDrawdownPct/100.0);
   if(daily_now && daily_latched==0.0)
     {
      if(GlobalVariableSet(daily_stop,1.0)==0)
         return false;
      daily_latched=1.0;
      GlobalVariablesFlush();
     }
   if(drawdown_now && peak_latched==0.0)
     {
      if(GlobalVariableSet(peak_stop,1.0)==0)
         return false;
      peak_latched=1.0;
      GlobalVariablesFlush();
     }
   breached=daily_now || drawdown_now || daily_latched>0.0 || peak_latched>0.0;
   if(breached)
      status_text="Persistent daily/drawdown risk stop - no new entries";
   return true;
  }

bool AcquireEntryMutex(double &token)
  {
   token = 0.0;
   string key = AccountKey("ENTRY_LOCK");
   // Atomic first creation: GlobalVariableSet() would overwrite another
   // chart's freshly acquired lease during a simultaneous first start.
   // GlobalVariableTemp() fails if the name already exists; never reset it.
   if(!GlobalVariableCheck(key) &&
      !GlobalVariableTemp(key) && !GlobalVariableCheck(key))
      return false;
   datetime now = TimeTradeServer();
   if(now <= 0)
      return false;
   double active = 0.0;
   if(!GlobalVariableGet(key, active))
      return false;
   // An orphan after crash cannot block DEMO indefinitely. Never steal
   // a lease younger than 300 seconds. Strictly atomic CAS, not read/write.
   token = (double)now;
   if(active == 0.0)
      return GlobalVariableSetOnCondition(key, token, 0.0);
   if(active > 0.0 && token > active+300.0)
      return GlobalVariableSetOnCondition(key, token, active);
   return false;
  }

void ReleaseEntryMutex(const double token)
  {
   if(token > 0.0)
     {
      string key=AccountKey("ENTRY_LOCK");
      if(!GlobalVariableSetOnCondition(key, 0.0, token))
         Print("QTS WARNING: entry mutex release mismatch (fail-closed)");
     }
  }

// Account-wide ownership: a duplicated EA instance cannot add exposure.
bool AnyConflictingPositionOrOrder()
  {
   for(int i=PositionsTotal()-1;i>=0;--i)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         return true; // Account state uncertain.
      if(PositionGetString(POSITION_SYMBOL)==_Symbol ||
         (ulong)PositionGetInteger(POSITION_MAGIC)==RobotMagic)
         return true;
     }
   for(int i=OrdersTotal()-1;i>=0;--i)
     {
      ulong ticket=OrderGetTicket(i);
      if(ticket==0 || !OrderSelect(ticket))
         return true;
      if(OrderGetString(ORDER_SYMBOL)==_Symbol ||
         (ulong)OrderGetInteger(ORDER_MAGIC)==RobotMagic)
         return true;
     }
   return false;
  }

int BrokerDailyEntryCount()
  {
   datetime begin=ServerMidnight();
   datetime now=TimeTradeServer();
   if(begin<=0 || now<begin || !HistorySelect(begin,now))
      return -1; // Fail closed when broker ledger is unavailable.
   ulong seen[];
   int count=0;
   int total=HistoryDealsTotal();
   for(int i=0;i<total;i++)
     {
      ulong ticket=HistoryDealGetTicket(i);
      if(ticket==0 || (ulong)HistoryDealGetInteger(ticket,DEAL_MAGIC)!=RobotMagic)
         continue;
      long entry=HistoryDealGetInteger(ticket,DEAL_ENTRY);
      if(entry!=DEAL_ENTRY_IN && entry!=DEAL_ENTRY_INOUT)
         continue;
      ulong order=(ulong)HistoryDealGetInteger(ticket,DEAL_ORDER);
      if(order==0)
         return -1;
      bool duplicate=false;
      for(int k=0;k<ArraySize(seen);k++)
         if(seen[k]==order) { duplicate=true;break; }
      if(duplicate)
         continue;
      int len=ArraySize(seen);
      if(ArrayResize(seen,len+1)!=len+1)
         return -1;
      seen[len]=order;
      count++;
     }
   return count;
  }

bool NewTradesAllowedByRisk()
  {
   double intent=0.0;
   if(!ReadNumber(AccountKey("SUBMIT_INTENT"),0.0,intent) || intent>0.0)
     {
      status_text="Unresolved submission: broker reconciliation required";
      return false;
     }
   double halt_state=0.0;
   if(local_execution_halt || !ReadNumber(AccountKey("EXEC_HALT"),0.0,halt_state) || halt_state>0.0)
     {
      status_text="Execution incident: manual broker reconciliation required";
      return false;
     }
   bool breached=false;
   if(!RiskState(AccountInfoDouble(ACCOUNT_EQUITY),breached) || breached)
      return false;
   int broker_count=BrokerDailyEntryCount();
   double stored_count=0.0;
   if(broker_count<0 || !ReadNumber(DayKey("COUNT"),0.0,stored_count))
     {
      status_text="Daily trade count unavailable";
      return false;
     }
   if(!TesterResearchNoDailyStops() &&
      MathMax(stored_count,(double)broker_count) >= (double)MaxTradesPerDay)
     {
      status_text="Daily entry limit reached";
      return false;
     }
   return true;
  }

bool BrokerSessionAllowed()
  {
   MqlDateTime dt;
   if(!TimeToStruct(TimeTradeServer(),dt))
      return false;
   if(dt.day_of_week==0 || dt.day_of_week==6)
      return false;
   if(dt.hour<BrokerStartHour || dt.hour>=BrokerEndHour)
      return false;
   int minute_of_day=dt.hour*60+dt.min;
   if(minute_of_day < RolloverBlackoutMin ||
      minute_of_day >= 1440-RolloverBlackoutMin)
      return false;
   return true;
  }

bool FreshEntryQuote(MqlTick &tick)
  {
   if(!SymbolInfoTick(_Symbol,tick))
      return false;
   if(tick.ask<=tick.bid || tick.bid<=0.0 || tick.time<=0 || _Point<=0.0)
      return false;
   datetime now=TimeTradeServer();
   if(now<tick.time || now-tick.time>MaxTickAgeSeconds)
      return false;
   double spread=tick.ask-tick.bid;
   double mid=(tick.ask+tick.bid)/2.0;
   if(spread/_Point > (double)MaxSpreadPoints ||
      spread*10000.0/mid > MaxSpreadBps)
      return false;
   if(AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)==0 ||
      AccountInfoInteger(ACCOUNT_TRADE_EXPERT)==0 ||
      TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)==0 ||
      MQLInfoInteger(MQL_TRADE_ALLOWED)==0)
      return false;
   if(SymbolInfoInteger(_Symbol,SYMBOL_TRADE_MODE)!=SYMBOL_TRADE_MODE_FULL)
      return false;
   long allowed=SymbolInfoInteger(_Symbol,SYMBOL_ORDER_MODE);
   if((allowed&SYMBOL_ORDER_LIMIT)==0 || (allowed&SYMBOL_ORDER_SL)==0 ||
      (allowed&SYMBOL_ORDER_TP)==0)
      return false;
   return true;
  }

// ------------------------------------------------------------------
// Research-only signal. Closed candles only, no lookahead.
// ------------------------------------------------------------------
int CompletedBarSignal(double &atr_value)
  {
   atr_value=0.0;
   if(BarsCalculated(fast_handle)<SlowEmaPeriod+3 ||
      BarsCalculated(slow_handle)<SlowEmaPeriod+3 ||
      BarsCalculated(atr_handle)<AtrPeriod+3 ||
      BarsCalculated(adx_handle)<AdxPeriod+3)
     {
      status_text="SIGNAL: indicators not ready";
      return 0;
     }
   double fast[2],slow[2],atr[1],adx[1],closes[2];
   MqlRates bars[3];
   if(CopyBuffer(fast_handle,0,1,2,fast)!=2 ||
      CopyBuffer(slow_handle,0,1,2,slow)!=2 ||
      CopyBuffer(atr_handle,0,1,1,atr)!=1 ||
      CopyBuffer(adx_handle,0,1,1,adx)!=1 ||
      CopyClose(_Symbol,SignalTimeframe,1,2,closes)!=2 ||
      CopyRates(_Symbol,SignalTimeframe,0,3,bars)!=3)
     {
      status_text="SIGNAL: missing indicator/bars";
      return 0;
     }
   int frame=PeriodSeconds(SignalTimeframe);
   if(frame<=0 || bars[1].time-bars[0].time!=frame ||
      bars[2].time-bars[1].time!=frame)
     {
      status_text="SIGNAL: stale or noncontiguous M5/M15 bars";
      return 0;
     }
   if(!MathIsValidNumber(atr[0]) || atr[0]<=0.0)
     {
      status_text="SIGNAL: invalid ATR";
      return 0;
     }
   if(!MathIsValidNumber(adx[0]) || adx[0]<MinimumAdx)
     {
      status_text=StringFormat("SIGNAL: ADX %.1f below threshold %.1f",adx[0],MinimumAdx);
      return 0;
     }
   int result=0;
   // Physical copy arrays are OLDEST first; index 0 is shift=2 here.
   if(fast[1]>slow[1] && closes[0]<=fast[0] && closes[1]>fast[1])
      result=1;
   if(fast[1]<slow[1] && closes[0]>=fast[0] && closes[1]<fast[1])
      result=-1;
   if(result==0)
     {
      status_text="SIGNAL: no closed-bar EMA pullback cross";
      return 0;
     }
   if(EnableH1TrendFilter)
     {
      double h1_ma[1],h1_close[1];
      // Requesting the buffer starts H1 indicator calculation in a cold tester/history cache.
      if(CopyBuffer(h1_handle,0,1,1,h1_ma)!=1 ||
         BarsCalculated(h1_handle)<55)
        {
         status_text="SIGNAL: H1 indicator not ready";
         return 0;
        }
      datetime h1_running=iTime(_Symbol,PERIOD_H1,0);
      datetime h1_previous=iTime(_Symbol,PERIOD_H1,1);
      if(h1_running<=0 || h1_running-h1_previous!=3600)
        {
         status_text="SIGNAL: H1 bar gap";
         return 0;
        } // Do not use a stale trend filter across the market weekend.
      if(CopyClose(_Symbol,PERIOD_H1,1,1,h1_close)!=1)
        {
         status_text="SIGNAL: no H1 close";
         return 0;
        }
      if(!MathIsValidNumber(h1_ma[0]) || h1_ma[0]==EMPTY_VALUE ||
         !MathIsValidNumber(h1_close[0]) || h1_close[0]<=0.0)
        {
         status_text="SIGNAL: H1 trend indicator invalid";
         return 0;
        }
      if((result>0 && h1_close[0]<=h1_ma[0]) ||
         (result<0 && h1_close[0]>=h1_ma[0]))
        {
         status_text="SIGNAL: H1 rejects M5/M15 entry direction";
         return 0;
        }
     }
   atr_value=atr[0];
   status_text=result>0 ? "SIGNAL: buy confirmed" : "SIGNAL: sell confirmed";
   return result;
  }

// After all signal globals and input declarations are available.
#include "StructureResearch.mqh"
#include "OpportunityResearch.mqh"

// ------------------------------------------------------------------
// Broker-authoritative order sizing and SL/TP attached to pending request.
// Broker stops are not guarantees of prices or maximum losses across gaps.
// ------------------------------------------------------------------
// Broker-quoted stop-loss risk plus explicit cost/slippage allowance.
// This is a conservative *budget*, NOT a guarantee of exit at the stop.
// Reject unaffordable broker minimum volumes; never weaken stop placement.
double EstimatedMonetaryLoss(const int side,const double volume,
                             const double entry,const double stop)
  {
   ENUM_ORDER_TYPE type=side>0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double stressed_stop=stop-(double)side*AdverseStopSlipPrice;
   if(stressed_stop<=0.0 || volume<=0.0)
      return -1.0;
   double pnl=0.0;
   if(!OrderCalcProfit(type,_Symbol,volume,entry,stressed_stop,pnl) ||
      !MathIsValidNumber(pnl) || pnl>=0.0)
      return -1.0;
   double cost=-pnl+AssumedRoundTurnFeePerLot*volume;
   return MathIsValidNumber(cost) && cost>0.0 ? cost : -1.0;
  }

// A current-equity breach latch prevents the NEXT trade after the limit.
// This additional pre-order budget prevents the NEXT stop from consuming
// more than the remaining daily loss allowance in the first place.
// No claim is made that a broker stop fill cannot slip beyond the budget.
double RemainingDailyRiskUsd(const double equity)
  {
   if(!MathIsValidNumber(equity) || equity<=0.0)
      return -1.0;
   if(TesterResearchNoDailyStops())
      return equity; // Per-trade cap still independently uses equity percentage.
   double day_start=0.0;
   // RiskState() must already have reconstructed/initialized this key.
   // Never silently replace a missing baseline with current equity.
   if(!GlobalVariableCheck(DayKey("START")) ||
      !ReadNumber(DayKey("START"),0.0,day_start) || day_start<=0.0)
      return -1.0;
   double remaining=equity-day_start*(1.0-MaxDailyLossPct/100.0);
   if(!MathIsValidNumber(remaining))
      return -1.0;
   return MathMax(0.0,remaining);
  }

bool PlannedOrderFitsRisk(const int side,const double volume,
                          const double entry,const double stop)
  {
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   double remaining=RemainingDailyRiskUsd(equity);
   double loss=EstimatedMonetaryLoss(side,volume,entry,stop);
   if(equity<=0.0 || remaining<=0.0 || loss<=0.0 ||
      loss>equity*EffectiveTradeRiskPct()/100.0+1e-8 ||
      loss>remaining+1e-8)
     {
      status_text="Planned stop exceeds per-trade or remaining daily risk";
      return false;
     }
   return true;
  }

double SizedLots(const int side,const double price,const double stop)
  {
   double minimum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double maximum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   if(minimum<=0.0 || maximum<minimum || step<=0.0 || equity<=0.0)
      return 0.0;
   double remaining=RemainingDailyRiskUsd(equity);
   if(remaining<=0.0)
      return 0.0;
   double budget=MathMin(equity*EffectiveTradeRiskPct()/100.0,remaining);
   double one_lot_cost=EstimatedMonetaryLoss(side,1.0,price,stop);
   if(one_lot_cost<=0.0 || budget<=0.0)
      return 0.0;
   double units=MathFloor(budget/(one_lot_cost*step)+1e-9);
   double volume=NormalizeDouble(MathMin(units*step,maximum),8);
   if(volume<minimum || !MathIsValidNumber(volume))
      return 0.0;
   double loss=EstimatedMonetaryLoss(side,volume,price,stop);
   if(loss<=0.0 || loss>budget+1e-8)
      return 0.0;
   ENUM_ORDER_TYPE type=side>0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double margin=0.0;
   double free_margin=AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(!OrderCalcMargin(type,_Symbol,volume,price,margin) ||
      margin<=0.0 || free_margin<=0.0 ||
      margin>free_margin*MaxMarginUsePct/100.0)
      return 0.0;
   return volume;
  }

// Owner-defined relocation: the former hypothetical stop becomes the LIMIT ENTRY.
// Long old plan: near support E_old, SL_old = swing low minus buffer.
// New plan: E_new = SL_old; SL_new = E_new - safe broker/volatility spacing.
// Short plan mirrors the logic above the previous swing high.
// These are CONTINUATION-BREAK risks: filling below support can be followed
// by a further decline. No claim that this reduces stop-out probabilities.
// Never change a LIMIT to a market order; refuse missing reward/price room.
bool PreparePullbackLimit(const int side,const MqlTick &tick,const double atr,
                          double &price,double &stop,double &target)
  {
   if(atr<=0.0 || !MathIsValidNumber(atr) || side==0)
      return false;
   double step=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(step<=0.0 || _Point<=0.0)
      return false;
   MqlRates recent[];
   if(CopyRates(_Symbol,SignalTimeframe,1,EntrySwingLookbackBars,recent)!=EntrySwingLookbackBars)
      return false;
   int frame=PeriodSeconds(SignalTimeframe);
   if(frame<=0)
      return false;
   double low=DBL_MAX, high=0.0;
   for(int i=0;i<EntrySwingLookbackBars;i++)
     {
      if(recent[i].low<=0.0 || recent[i].high<recent[i].low)
         return false;
      if(i>0 && recent[i].time-recent[i-1].time!=frame)
         return false; // Never bridge a weekend / missing bar interval.
      low=MathMin(low,recent[i].low);
      high=MathMax(high,recent[i].high);
     }
   double spread=tick.ask-tick.bid;
   if(spread<=0.0 || high<=low)
      return false;
   double min_broker=((double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)+2.0)*_Point;
   double min_pending=MathMax(min_broker,2.0*step);
   // The old structural SL is calculated unchanged using the earlier rule.
   double old_stop_buffer=MathMax(atr*StructuralStopBufferAtr,spread*1.2);
   // A new protective stop is placed BEYOND the former stop, not on entry.
   // Broker legality plus volatility and spread floors; never shrink below these.
   double minimum_risk=MathMax(atr*MinimumStopDistanceAtr,
                               MathMax(spread*MinimumStopSpreadMultiple,min_broker+2.0*step));
   double risk_ticks=MathCeil(minimum_risk/step-1e-9);
   if(risk_ticks<1.0)
      return false;
   double risk_distance=risk_ticks*step;
   if(side>0)
     {
      double old_stop=low-old_stop_buffer;
      // Exact old BUY stop tick is NOW the new BUY LIMIT entry price.
      price=NormalizeDouble(MathFloor(old_stop/step)*step,_Digits);
      stop=NormalizeDouble(price-risk_distance,_Digits);
      if(price<=0.0 || stop<=0.0 || stop>=price ||
         tick.bid-price<min_pending)
         return false;
      if(tick.ask-price>MaxPendingDistanceAtr*atr)
         return false;
      double risk=price-stop;
      if(risk<minimum_risk-step*0.51 || risk<min_broker)
         return false;
      target=NormalizeDouble(MathFloor((high-spread)/step)*step,_Digits);
      if(target<price+risk*RewardToRisk || target-price<min_broker)
         return false;
     }
   else
     {
      double old_stop=high+old_stop_buffer;
      // Exact old SELL stop tick is NOW the new SELL LIMIT entry price.
      price=NormalizeDouble(MathCeil(old_stop/step)*step,_Digits);
      stop=NormalizeDouble(price+risk_distance,_Digits);
      if(price<=0.0 || stop<=price || price-tick.ask<min_pending)
         return false;
      if(price-tick.bid>MaxPendingDistanceAtr*atr)
         return false;
      double risk=stop-price;
      if(risk<minimum_risk-step*0.51 || risk<min_broker)
         return false;
      target=NormalizeDouble(MathCeil((low+spread)/step)*step,_Digits);
      if(target>price-risk*RewardToRisk || price-target<min_broker || target<=0.0)
         return false;
     }
   return MathIsValidNumber(price) && MathIsValidNumber(stop) &&
          MathIsValidNumber(target);
  }

// Alternative near-market pullback LIMIT candidate for research only.
// Entry waits for a shallow retracement rather than a return beyond the swing.
// The stop MUST stay behind closed-bar structure. Targets never extend past
// the closed-bar extreme simply to manufacture a favorable R multiple.
bool PrepareRetestLimit(const int side,const MqlTick &tick,const double atr,
                        double &price,double &stop,double &target)
  {
   if(atr<=0.0 || !MathIsValidNumber(atr) || side==0)
      return false;
   double step=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(step<=0.0 || _Point<=0.0)
      return false;
   MqlRates recent[];
   if(CopyRates(_Symbol,SignalTimeframe,1,EntrySwingLookbackBars,recent)!=EntrySwingLookbackBars)
      return false;
   double low=recent[0].low, high=recent[0].high;
   int frame=PeriodSeconds(SignalTimeframe);
   if(frame<=0)
      return false;
   for(int i=1;i<EntrySwingLookbackBars;i++)
     {
      if(recent[i].time-recent[i-1].time!=frame)
         return false;
      low=MathMin(low,recent[i].low);
      high=MathMax(high,recent[i].high);
     }
   double spread=tick.ask-tick.bid;
   if(high<=low || spread<=0.0)
      return false;
   double broker_gap=((double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)+2.0)*_Point;
   double min_pending=MathMax(broker_gap,2.0*step);
   double depth=MathMax(atr*RetestDepthAtr,min_pending+step);
   double stop_buffer=MathMax(atr*StructuralStopBufferAtr,spread*MinimumStopSpreadMultiple);
   if(side>0)
     {
      price=NormalizeDouble(MathFloor((tick.bid-depth)/step)*step,_Digits);
      stop=NormalizeDouble(MathFloor((low-stop_buffer)/step)*step,_Digits);
      if(price<=0.0 || stop<=0.0 || stop>=price ||
         tick.bid-price<min_pending || tick.ask-price>MaxPendingDistanceAtr*atr)
         return false;
      double risk=price-stop;
      if(risk<MathMax(atr*MinimumStopDistanceAtr,broker_gap+2.0*step) ||
         risk<spread*MinimumStopSpreadMultiple)
         return false;
      target=NormalizeDouble(MathFloor((price+RewardToRisk*risk)/step)*step,_Digits);
      if(target>high-spread || target-price<broker_gap)
         return false;
     }
   else
     {
      price=NormalizeDouble(MathCeil((tick.ask+depth)/step)*step,_Digits);
      stop=NormalizeDouble(MathCeil((high+stop_buffer)/step)*step,_Digits);
      if(price<=0.0 || stop<=price || price-tick.ask<min_pending ||
         price-tick.bid>MaxPendingDistanceAtr*atr)
         return false;
      double risk=stop-price;
      if(risk<MathMax(atr*MinimumStopDistanceAtr,broker_gap+2.0*step) ||
         risk<spread*MinimumStopSpreadMultiple)
         return false;
      target=NormalizeDouble(MathCeil((price-RewardToRisk*risk)/step)*step,_Digits);
      if(target<low+spread || price-target<broker_gap || target<=0.0)
         return false;
     }
   return MathIsValidNumber(price) && MathIsValidNumber(stop) &&
          MathIsValidNumber(target);
  }

// Reject GTC orders: unattended orders may survive an EA stop or reboot.
// Pending requests always use RETURN per MT5's pending-order contract.
bool PendingExpiration(datetime &deadline)
  {
   long modes=SymbolInfoInteger(_Symbol,SYMBOL_EXPIRATION_MODE);
   if((modes&SYMBOL_EXPIRATION_SPECIFIED)==0)
      return false;
   datetime now=TimeTradeServer();
   datetime midnight=ServerMidnight();
   int frame=PeriodSeconds(SignalTimeframe);
   if(now<=0 || midnight<=0 || frame<=0)
      return false;
   datetime session_end=midnight+BrokerEndHour*3600-RolloverBlackoutMin*60;
   datetime desired=now+(datetime)(PendingExpiryBars*frame);
   deadline=desired<session_end ? desired : session_end;
   return deadline>now+60;
  }

// Exchange history and active book: rejected/cancelled pending attempts also
// count towards today's ceiling, independently of a local process restart.
int BrokerDailyPendingOrders()
  {
   datetime begin=ServerMidnight(),now=TimeTradeServer();
   if(begin<=0 || now<begin || !HistorySelect(begin,now))
      return -1;
   int count=0;
   for(int i=0;i<HistoryOrdersTotal();i++)
     {
      ulong ticket=HistoryOrderGetTicket(i);
      if(ticket==0)
         return -1;
      if((ulong)HistoryOrderGetInteger(ticket,ORDER_MAGIC)!=RobotMagic ||
         HistoryOrderGetString(ticket,ORDER_SYMBOL)!=_Symbol)
         continue;
      ENUM_ORDER_TYPE type=(ENUM_ORDER_TYPE)HistoryOrderGetInteger(ticket,ORDER_TYPE);
      if(type==ORDER_TYPE_BUY_LIMIT || type==ORDER_TYPE_SELL_LIMIT)
         count++;
     }
   for(int i=0;i<OrdersTotal();i++)
     {
      ulong ticket=OrderGetTicket(i);
      if(ticket==0 || !OrderSelect(ticket))
         return -1;
      if((ulong)OrderGetInteger(ORDER_MAGIC)!=RobotMagic ||
         OrderGetString(ORDER_SYMBOL)!=_Symbol ||
         (datetime)OrderGetInteger(ORDER_TIME_SETUP)<begin)
         continue;
      ENUM_ORDER_TYPE type=(ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if(type==ORDER_TYPE_BUY_LIMIT || type==ORDER_TYPE_SELL_LIMIT)
         count++;
     }
   return count;
  }

void LatchExecutionHalt(const string reason)
  {
   local_execution_halt=true;
   if(GlobalVariableSet(AccountKey("EXEC_HALT"),1.0)==0)
      Print("QTS CRITICAL: execution halt could not be persisted");
   GlobalVariablesFlush();
   status_text="EXECUTION HALTED - inspect broker pending orders and deals";
   Print("QTS execution incident: ",reason);
  }

// Only called under the atomic cross-chart entry mutex.
void EvaluateNewEntry()
  {
   if(AnyConflictingPositionOrOrder())
     {
      status_text="Another chart/strategy has a position or order";
      return;
     }
   if(!BrokerSessionAllowed())
     {
      status_text="ENTRY: outside broker session";
      return;
     }
   if(!NewTradesAllowedByRisk())
      return;
   MqlTick quote;
   if(!FreshEntryQuote(quote))
     {
      status_text="Quote, spread or broker permission refused entry";
      return;
     }
   double atr=0.0,structure_level=0.0,structure_anchor=0.0;
   bool structural=EntryStyle==QTS_BREAK_ACCEPT_RETEST ||
                   EntryStyle==QTS_SWEEP_RECLAIM;
   bool opportunity=(int)EntryStyle>=4;
   int side=opportunity ?
      CompletedOpportunitySignal(atr,structure_level,structure_anchor) :
      (structural ? CompletedStructureSignal(atr,structure_level,structure_anchor) :
                    CompletedBarSignal(atr));
   if(side==0)
      return; // Preserve the stage-specific reason from causal signal logic.
   if((quote.ask-quote.bid)>atr*MaxSpreadVsAtrPct/100.0)
     {
      status_text="Spread too large versus ATR";
      return;
     }
   int known=BrokerDailyPendingOrders();
   double stored_pending=0.0;
   if(known<0 || !ReadNumber(DayKey("PLACEMENTS"),0.0,stored_pending) ||
      (!TesterResearchNoDailyStops() &&
       MathMax((double)known,stored_pending)>=(double)MaxPendingOrdersPerDay))
     {
      status_text="Pending-order daily ceiling or broker history unavailable";
      return;
     }
   double price=0.0,stop=0.0,target=0.0;
   bool prepared=opportunity ?
      PrepareOpportunityLimit(side,quote,atr,structure_level,structure_anchor,price,stop,target) :
      (structural ?
       PrepareStructureLimit(side,quote,atr,structure_level,structure_anchor,price,stop,target) :
       (EntryStyle==QTS_RETEST_LIMIT ?
        PrepareRetestLimit(side,quote,atr,price,stop,target) :
        PreparePullbackLimit(side,quote,atr,price,stop,target)));
   if(!prepared)
     {
      status_text="LIMIT veto: price, structure, stop or reward not valid";
      return;
     }
   datetime deadline=0;
   if(!PendingExpiration(deadline))
     {
      status_text="Broker has no safe server-side pending expiration";
      return;
     }
   double lots=SizedLots(side,price,stop);
   if(lots<=0.0)
     {
      double min_lot=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
      double minimum_risk=EstimatedMonetaryLoss(side,min_lot,price,stop);
      double equity=AccountInfoDouble(ACCOUNT_EQUITY);
      double budget=MathMin(equity*EffectiveTradeRiskPct()/100.0,RemainingDailyRiskUsd(equity));
      double margin=0.0;
      ENUM_ORDER_TYPE order_side=side>0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      bool margin_ok=OrderCalcMargin(order_side,_Symbol,min_lot,price,margin);
      double margin_cap=AccountInfoDouble(ACCOUNT_MARGIN_FREE)*MaxMarginUsePct/100.0;
      if(minimum_risk>0.0 && minimum_risk>budget+1e-8)
         status_text=StringFormat("SIZE: min lot %.2f risks $%.2f, budget $%.2f",min_lot,minimum_risk,budget);
      else if(margin_ok && margin>margin_cap)
         status_text=StringFormat("MARGIN: min lot %.2f needs $%.2f, cap $%.2f",min_lot,margin,margin_cap);
      else
         status_text="SIZE: broker lot, loss model or margin rejected";
      return;
     }
   // For small accounts a near TP may be swallowed by trading fees.
   // OrderCalcProfit uses the broker contract and account currency; do not
   // treat this assumed-cost test as proof of positive expectancy.
   double gross_target=0.0;
   ENUM_ORDER_TYPE direction=side>0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(!OrderCalcProfit(direction,_Symbol,lots,price,target,gross_target) ||
      !MathIsValidNumber(gross_target) || gross_target<=0.0 ||
      gross_target<AssumedRoundTurnFeePerLot*lots*MinimumTargetFeeMultiple)
     {
      status_text="TP reward too small for assumed trading costs";
      return;
     }
   MqlTradeRequest request={};
   MqlTradeCheckResult check={};
   MqlTradeResult result={};
   request.action=TRADE_ACTION_PENDING;
   request.symbol=_Symbol;
   request.volume=lots;
   request.type=side>0 ? ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT;
   request.price=price;
   request.sl=stop;
   request.tp=target;
   request.magic=RobotMagic;
   request.deviation=(ulong)MaxDeviationPoints;
   request.type_filling=ORDER_FILLING_RETURN;
   request.type_time=ORDER_TIME_SPECIFIED;
   request.expiration=deadline;
   request.comment=EntryStyle==QTS_RETEST_LIMIT ? "QTS RETEST LIMIT DEMO" :
                   EntryStyle==QTS_FORMER_STOP_LIMIT ? "QTS OLD-SL LIMIT DEMO" :
                   EntryStyle==QTS_BREAK_ACCEPT_RETEST ? "QTS BREAK HOLD LIMIT" :
                   EntryStyle==QTS_SWEEP_RECLAIM ? "QTS SWEEP RECLAIM" :
                   EntryStyle==QTS_TREND_IMPULSE ? "QTS TREND IMPULSE" :
                   EntryStyle==QTS_RANGE_REJECTION ? "QTS RANGE REJECT" :
                                                     "QTS INSIDE BREAK";
   ResetLastError();
   if(!OrderCheck(request,check) || (check.retcode!=0 && check.retcode!=TRADE_RETCODE_DONE))
     {
      PrintFormat("QTS preflight rejected: retcode=%u error=%d %s",
                  check.retcode,GetLastError(),check.comment);
      status_text="Broker preflight refused";
      return;
     }
   // The order must remain a genuine unfilled limit; NEVER reprice it
   // to the live market or convert it to a market order on a price change.
   if(RealAccountBlocked() || !StrategyEvidenceApproved() ||
      !EnableDemoOrders || PauseNewEntries || EmergencyFlattenOwned ||
      AnyConflictingPositionOrOrder() || !FreshEntryQuote(quote) ||
      !BrokerSessionAllowed() || !NewTradesAllowedByRisk() ||
       !PlannedOrderFitsRisk(side,lots,price,stop))
     {
      status_text="Final execution/risk guard refused";
      return;
     }
   double level=((double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)+2.0)*_Point;
   if((side>0 && quote.bid-price<level) ||
      (side<0 && price-quote.ask<level) ||
      TimeTradeServer()>=deadline-30)
     {
      status_text="Price reached limit too soon; signal cancelled, no market entry";
      return;
     }
   // Write-ahead marker closes the crash window between send and receipt.
   // An unresolved marker blocks restart from submitting a second order.
   if(GlobalVariableSet(AccountKey("SUBMIT_INTENT"),(double)TimeTradeServer())==0)
     {
      LatchExecutionHalt("cannot persist submission intent");
      return;
     }
   GlobalVariablesFlush();
   ResetLastError();
   ulong started=GetTickCount64();
   bool sent=OrderSend(request,result);
   ulong elapsed_ms=GetTickCount64()-started;
   uint code=result.retcode;
   QTS_RECEIPT receipt=PendingReceipt(sent,code,result.order,result.deal);
   if(receipt==QTS_ACCEPTED)
     {
      double old_count=0.0;
      string key=DayKey("PLACEMENTS");
      if(!ReadNumber(key,0.0,old_count) ||
         GlobalVariableSet(key,old_count+1.0)==0)
        {
         // Broker has accepted the pending order. Cannot risk another one
         // if the attempt ledger was not durably written.
         LatchExecutionHalt("pending placement counter not durable");
         // The broker has already accepted this order. Attempt immediate
         // cancellation; timer-side retry still applies if this fails.
         trader.SetExpertMagicNumber(RobotMagic);
         trader.SetAsyncMode(false);
         if(!trader.OrderDelete(result.order) ||
            trader.ResultRetcode()!=TRADE_RETCODE_DONE)
            PrintFormat("QTS CRITICAL: immediate cancellation of unjournaled order %I64u failed",result.order);
         return;
        }
      if(GlobalVariableSet(AccountKey("SUBMIT_INTENT"),0.0)==0)
         LatchExecutionHalt("cannot commit submission receipt");
      GlobalVariablesFlush();
      PrintFormat("QTS DEMO LIMIT accepted order=%I64u side=%s lots=%.2f limit=%.5f SL=%.5f TP=%.5f expiry=%s response=%I64u ms",
                  result.order,side>0 ? "BUY_LIMIT":"SELL_LIMIT",lots,price,stop,target,
                  TimeToString(deadline,TIME_DATE|TIME_MINUTES),elapsed_ms);
      status_text="LIMIT submission accepted; fills confirmed only from broker deals";
     }
   else if(receipt==QTS_REJECTED)
     {
      if(GlobalVariableSet(AccountKey("SUBMIT_INTENT"),0.0)==0)
         LatchExecutionHalt("cannot persist definitive rejection");
      GlobalVariablesFlush();
      PrintFormat("QTS pending rejected without exposure: retcode=%u %s",code,result.comment);
      status_text="Broker rejected setup; wait for a new closed-bar signal";
     }
   else
     {
      PrintFormat("QTS pending submit unclear/refused: sent=%d retcode=%u order=%I64u deal=%I64u latency=%I64u ms error=%d",
                  (int)sent,code,result.order,result.deal,elapsed_ms,GetLastError());
      // A timeout or lost receipt can still leave an active pending order.
      // Never place another order until manual broker reconciliation.
      LatchExecutionHalt("ambiguous pending submission");
     }
  }

void ConsiderNewEntry()
  {
   if(!StrategyEvidenceApproved())
     {
      status_text="Research gate: no validated after-cost strategy; observation only";
      return;
     }
   if(!EnableDemoOrders)
     {
      status_text="ENTRY: disabled by EnableDemoOrders=false";
      return;
     }
   if(PauseNewEntries || EmergencyFlattenOwned || RealAccountBlocked())
     {
      status_text="ENTRY: operator pause, emergency mode or REAL-account block";
      return;
     }
   double token=0.0;
   if(!AcquireEntryMutex(token))
     {
      status_text="Another EA has the entry lock";
      return;
     }
   EvaluateNewEntry();
   ReleaseEntryMutex(token);
  }

// ------------------------------------------------------------------
// Existing positions: manage only the robot's exact magic, never manual.
// ------------------------------------------------------------------
// In a netting account, a pending order may merge with a manual position
// opened after placement. Cancel pending orders once any position appears.
// Dedicated DEMO account is still required to avoid unavoidable races.
bool AnySameSymbolPosition()
  {
   for(int i=PositionsTotal()-1;i>=0;--i)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket))
         return true; // Unreadable position book -> protective cancellation.
      if(PositionGetString(POSITION_SYMBOL)==_Symbol)
         return true;
     }
   return false;
  }

// Serialize protective requests across charts and throttle retries, including
// after restart. A partial close must be re-read from the position book first.
bool ProtectiveRequestDue(const ulong ticket,const string action)
  {
   string key=AccountKey(StringFormat("%s_%I64u",action,ticket));
   double previous=0.0;
   datetime now=TimeTradeServer();
   if(now<=0 || !ReadNumber(key,0.0,previous) || (double)now<previous+10.0)
      return false;
   if(!GlobalVariableSetOnCondition(key,(double)now,previous))
      return false;
   GlobalVariablesFlush();
   return true;
  }

// A pending LIMIT can be filled by the broker even after the original quote
// and spread have deteriorated. Cancel it opportunistically on every tick or
// timer when its original execution environment is no longer acceptable.
// Cancellation is best-effort: a broker fill can race the request.
bool RestingPendingQuoteSafe()
  {
   MqlTick quote={};
   if(!SymbolInfoTick(_Symbol,quote) || _Point<=0.0 ||
      quote.bid<=0.0 || quote.ask<=quote.bid || quote.time<=0)
      return false;
   datetime now=TimeTradeServer();
   if(now<=0 || now<quote.time || now-quote.time>MaxTickAgeSeconds)
      return false;
   double spread=quote.ask-quote.bid;
   double mid=(quote.bid+quote.ask)/2.0;
   if(mid<=0.0 || spread/_Point>(double)MaxSpreadPoints ||
      spread*10000.0/mid>MaxSpreadBps)
      return false;
   // Apply the same ATR-normalized spread policy to a RESTING order, not
   // only at submission. Never accept missing indicator data as safe.
   double atr[1];
   if(CopyBuffer(atr_handle,0,1,1,atr)!=1 ||
      !MathIsValidNumber(atr[0]) || atr[0]<=0.0 ||
      spread>atr[0]*MaxSpreadVsAtrPct/100.0)
      return false;
   return true;
  }

void ManageOwnedPendingOrders(const bool force_cancel=false)
  {
   if(RealAccountBlocked())
      return;
   bool breached=false;
   bool risk_ok=RiskState(AccountInfoDouble(ACCOUNT_EQUITY),breached);
   // Do not burden the quote/ATR pipeline when no pending orders are open.
   bool pending_quote_unsafe=OrdersTotal()>0 && !RestingPendingQuoteSafe();
   // A resting order can fill while Algo Trading is paused. On receipt of
   // a timer/tick, attempt cancellation whenever any safety state worsens.
   bool cancel_all=force_cancel || pending_quote_unsafe ||
                   EmergencyFlattenOwned || PauseNewEntries ||
                   !EnableDemoOrders || !StrategyEvidenceApproved() || !risk_ok || breached ||
                   !BrokerSessionAllowed() || local_execution_halt ||
                   AnySameSymbolPosition();
   double persistent_halt=0.0;
   if(!ReadNumber(AccountKey("EXEC_HALT"),0.0,persistent_halt) ||
      persistent_halt>0.0)
      cancel_all=true;
   datetime now=TimeTradeServer();
   for(int i=OrdersTotal()-1;i>=0;--i)
     {
      ulong ticket=OrderGetTicket(i);
      if(ticket==0 || !OrderSelect(ticket))
        {
         LatchExecutionHalt("could not inspect active order during protective check");
         continue;
        }
      if((ulong)OrderGetInteger(ORDER_MAGIC)!=RobotMagic ||
         OrderGetString(ORDER_SYMBOL)!=_Symbol)
         continue;
      ENUM_ORDER_TYPE type=(ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if(type!=ORDER_TYPE_BUY_LIMIT && type!=ORDER_TYPE_SELL_LIMIT)
         continue;
      datetime expiry=(datetime)OrderGetInteger(ORDER_TIME_EXPIRATION);
      double price=OrderGetDouble(ORDER_PRICE_OPEN);
      double sl=OrderGetDouble(ORDER_SL),tp=OrderGetDouble(ORDER_TP);
      bool malformed=price<=0.0 || sl<=0.0 || tp<=0.0 ||
                     (type==ORDER_TYPE_BUY_LIMIT && (sl>=price || tp<=price)) ||
                     (type==ORDER_TYPE_SELL_LIMIT && (sl<=price || tp>=price));
      // Server expiry is primary; local cancel is additional best effort.
      bool stale=expiry<=0 || now>=expiry || malformed;
      if(!cancel_all && !stale)
         continue;
      if(!ProtectiveRequestDue(ticket,"CANCEL"))
         continue;
      trader.SetExpertMagicNumber(RobotMagic);
      trader.SetAsyncMode(false);
      bool ok=trader.OrderDelete(ticket);
      uint ret=trader.ResultRetcode();
      if(!ok || ret!=TRADE_RETCODE_DONE)
        {
         // Expiry/fill/cancellation may win the race against this delete.
         if(!OrderSelect(ticket) && HistoryOrderSelect(ticket))
           {
            long state=HistoryOrderGetInteger(ticket,ORDER_STATE);
            if(state==ORDER_STATE_FILLED || state==ORDER_STATE_CANCELED ||
               state==ORDER_STATE_EXPIRED)
               continue;
           }
         PrintFormat("QTS protective pending cancellation failed: order=%I64u ret=%u",ticket,ret);
         LatchExecutionHalt("unable to cancel resting pending order");
        }
      else if(OrderSelect(ticket))
        {
         // A successful request reply does not mean the broker-side book
         // has definitely stopped exposing the resting order yet.
         PrintFormat("QTS WARNING: cancellation acknowledged but pending order=%I64u still visible",ticket);
         // Keep entry vetoed by the existing order; recheck on the timer.
         // Immediate cache visibility is not a definitive cancellation failure.
        }
      else
         PrintFormat("QTS pending order removed: ticket=%I64u",ticket);
     }
  }

void ManageOwnedPositions()
  {
   if(RealAccountBlocked())
      return;
   bool risk_breach=false;
   bool risk_ok=RiskState(AccountInfoDouble(ACCOUNT_EQUITY),risk_breach);
   bool stop_risk=(!risk_ok || risk_breach);
   for(int i=PositionsTotal()-1;i>=0;--i)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket))
         continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=RobotMagic)
         continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol)
        {
         // On another instrument/chart, we refuse to close it blindly.
         status_text="Robot magic holds position on another symbol";
         continue;
        }
      double sl=PositionGetDouble(POSITION_SL);
      double tp=PositionGetDouble(POSITION_TP);
      datetime opened=(datetime)PositionGetInteger(POSITION_TIME);
      bool expired=opened>0 && TimeTradeServer()-opened>=MaxPositionMinutes*60;
      bool must_close=EmergencyFlattenOwned || sl<=0.0 || tp<=0.0 ||
                      expired || (FlattenOnEquityBreach && stop_risk);
      if(!must_close)
         continue;
      if(!ProtectiveRequestDue(ticket,"CLOSE"))
         continue;
      trader.SetExpertMagicNumber(RobotMagic);
      trader.SetDeviationInPoints(MaxDeviationPoints);
      trader.SetTypeFillingBySymbol(_Symbol);
      trader.SetAsyncMode(false);
      bool sent=trader.PositionClose(ticket);
      uint code=trader.ResultRetcode();
      if(!sent || (code!=TRADE_RETCODE_DONE && code!=TRADE_RETCODE_DONE_PARTIAL))
        {
         PrintFormat("QTS CRITICAL: protective close FAILED, position=%I64u ret=%u",ticket,code);
         LatchExecutionHalt("protective close failed or broker outcome unknown");
        }
      else if(code==TRADE_RETCODE_DONE_PARTIAL)
        {
         // A partial close leaves broker exposure. Never call it flat.
         PrintFormat("QTS CRITICAL: partial protective close, remaining position=%I64u",ticket);
         // Residual position remains under management; next request uses
         // refreshed remaining volume after the cross-chart throttle.
        }
      else if(PositionSelectByTicket(ticket))
        {
         // Terminal position cache can lag the broker receipt. Refuse any
         // new exposure until the operator confirms actual broker closure.
         PrintFormat("QTS WARNING: broker acknowledged close but position %I64u still visible",ticket);
         // Continue protective management; cache convergence is asynchronous.
        }
      else
        {
         PrintFormat("QTS protective close confirmed removed: position=%I64u",ticket);
         status_text="Robot position closed";
        }
     }
  }

void DisplayStatus()
  {
   string mode=MQLInfoInteger(MQL_TESTER)!=0 ? "STRATEGY TESTER" :
               (ConnectedDemoForwardAuthorized() ? "WMMarkets DEMO FORWARD" : "DEMO OBSERVE ONLY");
   string operation=EnableDemoOrders && StrategyEvidenceApproved() && !PauseNewEntries && !EmergencyFlattenOwned ?
                    (MQLInfoInteger(MQL_TESTER)!=0 ?
                     (TesterResearchNoDailyStops() ? "TESTER: DAILY LIMITS OFF" : "TESTER: DAILY LIMITS ON") :
                     "WMMarkets DEMO FORWARD: DAILY LIMITS ON") : "NO NEW ORDERS";
   MqlTick current={};
   double spread=0.0;
   if(SymbolInfoTick(_Symbol,current) && _Point>0.0 && current.ask>current.bid)
      spread=(current.ask-current.bid)/_Point;
   Comment("QTS GOLD ROBOT | ",mode," | LIVE LOCKED\n",
           operation," | EntryStyle=",IntegerToString((int)EntryStyle),"\n",
           "Equity=",DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),2),
           " ",AccountInfoString(ACCOUNT_CURRENCY),
           " | Effective trade risk=",DoubleToString(EffectiveTradeRiskPct(),2),"%",
           " | Spread=",DoubleToString(spread,1),"pt\n",
           "NO VALIDATED EDGE | No guaranteed profit\n",
           status_text);
  }

int OnInit()
  {
   if(!DemoOrTester())
     {
      Print("QTS: LIVE/CONTEST account refused. DEMO or TESTER ONLY.");
      return INIT_FAILED;
     }
   if(StringFind(_Symbol,"XAUUSD")!=0 && StringFind(_Symbol,"GOLD")!=0)
     {
      Print("QTS: only XAUUSD/GOLD with broker suffixes supported.");
      return INIT_FAILED;
     }
   if(SignalTimeframe!=PERIOD_M5 && SignalTimeframe!=PERIOD_M15 &&
      SignalTimeframe!=PERIOD_M30 &&
      SignalTimeframe!=PERIOD_H1)
      return INIT_PARAMETERS_INCORRECT;
   // Extra hypotheses remain Tester-only until independently accepted.
   if((int)EntryStyle<0 || (int)EntryStyle>6 ||
      ((int)EntryStyle>=4 && MQLInfoInteger(MQL_TESTER)==0) ||
      StructureBreakConfirmAtr<0.01 || StructureBreakConfirmAtr>0.70 ||
      StructureRetestWindowAtr<0.05 || StructureRetestWindowAtr>1.50 ||
      StructureEntryOffsetAtr<0.0 || StructureEntryOffsetAtr>0.50 ||
      FastEmaPeriod<3 || SlowEmaPeriod<=FastEmaPeriod || AtrPeriod<2 ||
      AdxPeriod<2 || MinimumAdx<1.0 ||
      RewardToRisk<0.7 || RewardToRisk>4.0 || RiskPerTradePct<=0.0 || RiskPerTradePct>2.0 ||
      DemoForwardRiskCapPct<=0.0 || DemoForwardRiskCapPct>0.5 ||
      MaxDailyLossPct<=0.0 || MaxDailyLossPct>5.0 ||
      MaxPeakDrawdownPct<=MaxDailyLossPct || MaxPeakDrawdownPct>12.0 ||
      MaxTradesPerDay<1 || MaxTradesPerDay>20 || MaxSpreadPoints<=0 ||
      MaxSpreadBps<=0.0 || MaxSpreadVsAtrPct<=0.0 || MaxSpreadVsAtrPct>50.0 ||
      MaxTickAgeSeconds<1 || MaxPositionMinutes<15 ||
      MaxMarginUsePct<=0.0 || MaxMarginUsePct>50.0 ||
      BrokerStartHour<0 || BrokerStartHour>23 ||
      BrokerEndHour<1 || BrokerEndHour>24 || BrokerStartHour>=BrokerEndHour ||
      RolloverBlackoutMin<0 || RolloverBlackoutMin>120 ||
      RobotMagic==0 || MaxDeviationPoints<=0 ||
      EntrySwingLookbackBars<5 || EntrySwingLookbackBars>30 ||
      StructuralStopBufferAtr<0.10 || StructuralStopBufferAtr>1.00 ||
      MinimumStopDistanceAtr<0.15 || MinimumStopDistanceAtr>2.50 ||
      MinimumStopSpreadMultiple<2.0 || MinimumStopSpreadMultiple>10.0 ||
      MaxPendingDistanceAtr<1.0 || MaxPendingDistanceAtr>4.0 ||
      PendingExpiryBars<1 || PendingExpiryBars>4 ||
      MaxPendingOrdersPerDay<1 || MaxPendingOrdersPerDay>40 ||
      RetestDepthAtr<0.1 || RetestDepthAtr>1.5 ||
      AssumedRoundTurnFeePerLot<0.0 || AssumedRoundTurnFeePerLot>100.0 ||
      AdverseStopSlipPrice<0.0 || AdverseStopSlipPrice>2.0 ||
      MinimumTargetFeeMultiple<1.0 || MinimumTargetFeeMultiple>10.0)
     {
      Print("QTS: invalid parameters, no initialization.");
      return INIT_PARAMETERS_INCORRECT;
     }
   fast_handle=iMA(_Symbol,SignalTimeframe,FastEmaPeriod,0,MODE_EMA,PRICE_CLOSE);
   slow_handle=iMA(_Symbol,SignalTimeframe,SlowEmaPeriod,0,MODE_EMA,PRICE_CLOSE);
   atr_handle=iATR(_Symbol,SignalTimeframe,AtrPeriod);
   adx_handle=iADX(_Symbol,SignalTimeframe,AdxPeriod);
   if(EnableH1TrendFilter)
      h1_handle=iMA(_Symbol,PERIOD_H1,50,0,MODE_EMA,PRICE_CLOSE);
   if(fast_handle==INVALID_HANDLE || slow_handle==INVALID_HANDLE ||
      atr_handle==INVALID_HANDLE || adx_handle==INVALID_HANDLE ||
      (EnableH1TrendFilter && h1_handle==INVALID_HANDLE))
     {
      Print("QTS: indicator initialization failed.");
      return INIT_FAILED;
     }
   trader.SetExpertMagicNumber(RobotMagic);
   trader.SetDeviationInPoints(MaxDeviationPoints);
   trader.SetTypeFillingBySymbol(_Symbol);
   trader.SetAsyncMode(false);
   bool breached=false;
   if(!RiskState(AccountInfoDouble(ACCOUNT_EQUITY),breached))
     {
      Print("QTS: cannot initialize durable equity risk baseline.");
      return INIT_FAILED;
     }
   if(ResetExecutionHalt)
     {
      // This explicit operator flag should only be used AFTER confirming
      // broker positions, active orders and trade/deal history manually.
      if(AnyConflictingPositionOrOrder() || !HistorySelect(0,TimeTradeServer()))
        {
         Print("QTS: cannot reset execution halt with outstanding exposure.");
         return INIT_FAILED;
        }
      if(GlobalVariableSet(AccountKey("EXEC_HALT"),0.0)==0)
        {
         Print("QTS: could not clear persistent execution halt.");
         return INIT_FAILED;
        }
      if(GlobalVariableSet(AccountKey("SUBMIT_INTENT"),0.0)==0)
         return INIT_FAILED;
      GlobalVariablesFlush();
      Print("QTS WARNING: operator explicitly cleared execution halt after reconciliation.");
     }
   // No old signal gets executed when attaching/restarting the expert.
   last_closed_bar=iTime(_Symbol,SignalTimeframe,1);
   if(!EventSetTimer(10))
     {
      // MT5 timers are the second independent path for pending cancellation
      // and time-based exits during quiet periods. Do not arm an EA without
      // that protective monitoring path, even on a demo account.
      Print("QTS CRITICAL: protective timer could not be registered; refusing startup.");
      return INIT_FAILED;
     }
   if(MQLInfoInteger(MQL_TESTER)!=0)
      audit_file=StringFormat("QTS_tester_deals_%I64u.csv",GetTickCount64());
   if(!ReconcileBrokerDealAudit())
      LatchExecutionHalt("restart deal history reconciliation failed");
   broker_was_connected=(bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   if(MQLInfoInteger(MQL_TESTER)!=0)
      status_text=EnableDemoOrders ? "Strategy Tester research enabled" :
                                     "Strategy Tester observation only";
   else
      status_text=ConnectedDemoForwardAuthorized() ?
                  "UNVALIDATED: WMMarkets DEMO-forward trial explicitly enabled" :
                  "DEMO observation: two forward authorization inputs required";
   PrintFormat("QTS Gold Robot research: entry_style=%d tester_no_daily_stops=%d; LIVE blocked; edge UNVALIDATED.",
               (int)EntryStyle,(int)TesterResearchNoDailyStops());
   DisplayStatus();
   return INIT_SUCCEEDED;
  }

// Append broker-authoritative DEAL facts locally. These are not synthetic
// backtest fills or a complete PnL statement: fees can post subsequently.
// No network access, credentials, order tickets from other experts or trades.
// This local CSV is supplementary; the broker's history is the authority.
// Open the file for one writer (FILE_SHARE_WRITE deliberately omitted) and
// check its durable contents before append. Temporary terminal variables are
// NOT durable deduplication keys and must not conceal a failed file write.
bool AppendBrokerDealAudit(const ulong deal, const long broker_time_msc,
                           const long direction, const double volume,
                           const double price,
                           const double gross, const double commission,
                           const double swap, const double fee,
                           const double provisional_net)
  {
   int flags=FILE_COMMON|FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_SHARE_READ;
   if(MQLInfoInteger(MQL_TESTER)!=0) flags &= ~FILE_COMMON;
   ResetLastError();
   int file=FileOpen(audit_file,flags,';');
   if(file==INVALID_HANDLE)
     {
      PrintFormat("QTS AUDIT: exclusive writer could not open broker ledger, error=%d",GetLastError());
      return false;
     }
   // Exactly 15 columns are written below. A partial/corrupt historical row
   // blocks append rather than letting another broker receipt disappear.
   string deal_key=StringFormat("%I64u",deal);
   string login_key=StringFormat("%I64d",AccountInfoInteger(ACCOUNT_LOGIN));
   string magic_key=StringFormat("%I64u",RobotMagic);
   string broker=AccountInfoString(ACCOUNT_SERVER);
   while(!FileIsEnding(file))
     {
      string fields[15];
      for(int i=0;i<15;i++)
        {
         if(FileIsEnding(file))
           {
            FileClose(file);
            Print("QTS AUDIT: truncated historical CSV row - manual inspection required");
            return false;
           }
         fields[i]=FileReadString(file);
        }
      if(fields[2]==broker && fields[3]==login_key &&
         fields[5]==magic_key && fields[6]==deal_key)
        {
         FileClose(file);
         return true; // Durable existing record, including after restart.
        }
     }
   FileSeek(file,0,SEEK_END);
   uint written=FileWrite(file,broker_time_msc,
                          TimeToString(TimeTradeServer(),TIME_DATE|TIME_SECONDS),
                          broker,(long)AccountInfoInteger(ACCOUNT_LOGIN),_Symbol,
                          (long)RobotMagic,deal,direction,
                          DoubleToString(volume,8),DoubleToString(price,_Digits),
                          DoubleToString(gross,8),DoubleToString(commission,8),
                          DoubleToString(swap,8),DoubleToString(fee,8),
                          DoubleToString(provisional_net,8));
   FileFlush(file);
   FileClose(file);
   if(written==0)
     {
      Print("QTS AUDIT: broker deal append failed - inspect broker history");
      return false;
     }
   return true;
  }

// Recover receipts missed while stopped/disconnected. History is authoritative;
// the durable CSV deduplicates repeated events and replayed receipts.
bool ReconcileBrokerDealAudit()
  {
   if(!HistorySelect(0,TimeTradeServer())) return false;
   for(int i=0;i<HistoryDealsTotal();i++)
     {
      ulong deal=HistoryDealGetTicket(i);
      if(deal==0) return false;
      if((ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)!=RobotMagic ||
         HistoryDealGetString(deal,DEAL_SYMBOL)!=_Symbol) continue;
      double gross=HistoryDealGetDouble(deal,DEAL_PROFIT);
      double commission=HistoryDealGetDouble(deal,DEAL_COMMISSION);
      double swap=HistoryDealGetDouble(deal,DEAL_SWAP);
      double fee=HistoryDealGetDouble(deal,DEAL_FEE);
      if(!AppendBrokerDealAudit(deal,HistoryDealGetInteger(deal,DEAL_TIME_MSC),
                                HistoryDealGetInteger(deal,DEAL_TYPE),
                                HistoryDealGetDouble(deal,DEAL_VOLUME),
                                HistoryDealGetDouble(deal,DEAL_PRICE),
                                gross,commission,swap,fee,gross+commission+swap+fee))
         return false;
     }
   return true;
  }

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(RealAccountBlocked())
      return;
   // Broker deal history remains the durable authority. Terminal Experts
   // messages are supplemental, and may not arrive in deterministic order.
   if(trans.type==TRADE_TRANSACTION_REQUEST)
     {
      if(request.magic==RobotMagic && request.symbol==_Symbol)
         PrintFormat("QTS request receipt: order=%I64u deal=%I64u retcode=%u",
                     result.order,result.deal,result.retcode);
      return;
     }
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD || trans.deal==0 ||
      trans.symbol!=_Symbol)
      return;
   if(!HistoryDealSelect(trans.deal))
     {
      // The deal event cannot be attributed safely until its broker record
      // is readable. Never silently treat an absent receipt as a clean trade.
      LatchExecutionHalt("broker deal event could not be read from history");
      return;
     }
   if((ulong)HistoryDealGetInteger(trans.deal,DEAL_MAGIC)!=RobotMagic ||
      HistoryDealGetString(trans.deal,DEAL_SYMBOL)!=_Symbol)
      return;
   double gross=HistoryDealGetDouble(trans.deal,DEAL_PROFIT);
   double commission=HistoryDealGetDouble(trans.deal,DEAL_COMMISSION);
   double swap=HistoryDealGetDouble(trans.deal,DEAL_SWAP);
   double fee=HistoryDealGetDouble(trans.deal,DEAL_FEE);
   long direction=HistoryDealGetInteger(trans.deal,DEAL_TYPE);
   long broker_event_time_msc=HistoryDealGetInteger(trans.deal,DEAL_TIME_MSC);
   double volume=HistoryDealGetDouble(trans.deal,DEAL_VOLUME);
   double fill_price=HistoryDealGetDouble(trans.deal,DEAL_PRICE);
   double realized=gross+commission+swap+fee;
   PrintFormat("QTS broker deal: deal=%I64u entry=%d volume=%.2f price=%.5f gross=%.2f commission=%.2f swap=%.2f fee=%.2f net=%.2f",
               trans.deal,(int)HistoryDealGetInteger(trans.deal,DEAL_ENTRY),
               volume,fill_price,gross,commission,swap,fee,realized);
   // Broker says whether exit was SL, TP, stop-out or another reason.
   // It cannot prove that the original signal was economically sound.
   PrintFormat("QTS FORENSIC DEAL: deal=%I64u position=%I64d order=%I64d entry=%s reason=%s type=%s time_msc=%I64d volume=%.8f price=%.5f sl=%.5f tp=%.5f gross=%.8f commission=%.8f swap=%.8f fee=%.8f",
               trans.deal,HistoryDealGetInteger(trans.deal,DEAL_POSITION_ID),
               HistoryDealGetInteger(trans.deal,DEAL_ORDER),
               EnumToString((ENUM_DEAL_ENTRY)HistoryDealGetInteger(trans.deal,DEAL_ENTRY)),
               EnumToString((ENUM_DEAL_REASON)HistoryDealGetInteger(trans.deal,DEAL_REASON)),
               EnumToString((ENUM_DEAL_TYPE)HistoryDealGetInteger(trans.deal,DEAL_TYPE)),
               broker_event_time_msc,volume,fill_price,
               HistoryDealGetDouble(trans.deal,DEAL_SL),
               HistoryDealGetDouble(trans.deal,DEAL_TP),
               gross,commission,swap,fee);
   if(!AppendBrokerDealAudit(trans.deal, broker_event_time_msc, direction,
                             volume, fill_price, gross, commission,
                             swap, fee, realized))
     {
      // A lost accounting record must be conspicuous, but not cause an
      // unsafe automatic market-side replay of the broker transaction.
      LatchExecutionHalt("broker transaction ledger could not be appended");
     }
  }

// Tester-only complete, broker-authoritative position/deal evidence.
// File is in Terminal Common/Files, copied by the automatic Windows runner.
// Deliberately excludes account numbers and user credentials.
double OnTester()
  {
   if(MQLInfoInteger(MQL_TESTER)==0) return 0.0;
   if(!HistorySelect(0,TimeCurrent()))
     {
      Print("QTS FORENSIC ERROR: tester history could not be selected");
      return 0.0;
     }
   string filename=StringFormat("QTS_FORENSIC_STYLE_%d_%I64u.csv",
                   (int)EntryStyle,GetTickCount64());
   int f=FileOpen(filename,FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,';');
   if(f==INVALID_HANDLE)
     {
      PrintFormat("QTS FORENSIC ERROR: common file unavailable err=%d",GetLastError());
      return 0.0;
     }
   FileWrite(f,"position_id","deal_id","order_id","entry","reason",
             "type","time_msc","volume","price","sl","tp",
             "gross","commission","swap","fee","setup_reason");
   int count=0;
   for(int i=0;i<HistoryDealsTotal();i++)
     {
      ulong deal=HistoryDealGetTicket(i);
      if(deal==0) continue;
      if((ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)!=RobotMagic ||
         HistoryDealGetString(deal,DEAL_SYMBOL)!=_Symbol) continue;
      ENUM_DEAL_ENTRY entry=(ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal,DEAL_ENTRY);
      if(entry!=DEAL_ENTRY_IN && entry!=DEAL_ENTRY_OUT &&
         entry!=DEAL_ENTRY_INOUT && entry!=DEAL_ENTRY_OUT_BY) continue;
      ulong order=(ulong)HistoryDealGetInteger(deal,DEAL_ORDER);
      // Broker order comments document the proposed entry family.
      // These comments may be empty/modified by the broker; never invent one.
      string setup_reason="";
      if(entry==DEAL_ENTRY_IN && order!=0)
         setup_reason=HistoryOrderGetString(order,ORDER_COMMENT);
      // Some brokers omit DEAL_SL/TP on the opening deal. Historical
      // ORDER_SL/TP are a documented fallback, not proof of a later edit.
      double deal_sl=HistoryDealGetDouble(deal,DEAL_SL);
      double deal_tp=HistoryDealGetDouble(deal,DEAL_TP);
      if(entry==DEAL_ENTRY_IN && order!=0)
        {
         if(deal_sl<=0.0) deal_sl=HistoryOrderGetDouble(order,ORDER_SL);
         if(deal_tp<=0.0) deal_tp=HistoryOrderGetDouble(order,ORDER_TP);
        }
      FileWrite(f,HistoryDealGetInteger(deal,DEAL_POSITION_ID),deal,
                order,
                EnumToString(entry),
                EnumToString((ENUM_DEAL_REASON)HistoryDealGetInteger(deal,DEAL_REASON)),
                EnumToString((ENUM_DEAL_TYPE)HistoryDealGetInteger(deal,DEAL_TYPE)),
                HistoryDealGetInteger(deal,DEAL_TIME_MSC),
                DoubleToString(HistoryDealGetDouble(deal,DEAL_VOLUME),8),
                DoubleToString(HistoryDealGetDouble(deal,DEAL_PRICE),_Digits),
                DoubleToString(deal_sl,_Digits),
                DoubleToString(deal_tp,_Digits),
                DoubleToString(HistoryDealGetDouble(deal,DEAL_PROFIT),8),
                DoubleToString(HistoryDealGetDouble(deal,DEAL_COMMISSION),8),
                DoubleToString(HistoryDealGetDouble(deal,DEAL_SWAP),8),
                DoubleToString(HistoryDealGetDouble(deal,DEAL_FEE),8),
                setup_reason);
      count++;
     }
   FileFlush(f);
   FileClose(f);
   PrintFormat("QTS FORENSIC EXPORT: style=%d rows=%d file=%s",
               (int)EntryStyle,count,filename);
   return 0.0; // No optimization or edge selection at this callback.
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   // Removing/restarting the EA is not authorization to leave a new order
   // resting indefinitely; server expiry remains primary if offline.
   if(!RealAccountBlocked())
      ManageOwnedPendingOrders(true);
   Comment("");
   if(fast_handle!=INVALID_HANDLE) IndicatorRelease(fast_handle);
   if(slow_handle!=INVALID_HANDLE) IndicatorRelease(slow_handle);
   if(atr_handle!=INVALID_HANDLE) IndicatorRelease(atr_handle);
   if(adx_handle!=INVALID_HANDLE) IndicatorRelease(adx_handle);
   if(h1_handle!=INVALID_HANDLE) IndicatorRelease(h1_handle);
  }

void OnTimer()
  {
   if(RealAccountBlocked())
      return;
   ManageOwnedPendingOrders();
   ManageOwnedPositions();
   bool connected=(bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   if(connected && !broker_was_connected && !ReconcileBrokerDealAudit())
      LatchExecutionHalt("reconnected deal history reconciliation failed");
   broker_was_connected=connected;
   DisplayStatus();
  }

// An unarmed DEMO should still explain which CLOSED-BAR signal conditions
// passed or failed. This function has NO order preparation or submission path.
// It lets operators diagnose missed signals without enabling Demo Forward.
void ObserveUnarmedDemoSignal()
  {
   if(MQLInfoInteger(MQL_TESTER)!=0 || RealAccountBlocked() ||
      !EnableEntryDiagnostics || ConnectedDemoForwardAuthorized())
      return;
   double atr=0.0,level=0.0,anchor=0.0;
   bool structural=EntryStyle==QTS_BREAK_ACCEPT_RETEST ||
                   EntryStyle==QTS_SWEEP_RECLAIM;
   bool opportunity=(int)EntryStyle>=4;
   int side=opportunity ? CompletedOpportunitySignal(atr,level,anchor) :
      (structural ? CompletedStructureSignal(atr,level,anchor) : CompletedBarSignal(atr));
   if(side>0)
      status_text="OBSERVE: unvalidated BUY candidate; orders not authorized";
   else if(side<0)
      status_text="OBSERVE: unvalidated SELL candidate; orders not authorized";
   // For no candidate, retain the precise signal veto reason.
  }

void OnTick()
  {
   if(RealAccountBlocked())
     {
      Comment("QTS GOLD ROBOT: LIVE ACCOUNT BLOCKED");
      return;
     }
   ManageOwnedPendingOrders();
   ManageOwnedPositions();
   datetime closed=iTime(_Symbol,SignalTimeframe,1);
   if(closed>0 && last_closed_bar>0 && closed!=last_closed_bar)
     {
      last_closed_bar=closed;
      ConsiderNewEntry();
      ObserveUnarmedDemoSignal();
      // Closed-bar diagnostics also work on WMMarkets connected DEMO.
      // Logs are observational and never authorize orders or contain logins.
      if(EnableEntryDiagnostics &&
         (MQLInfoInteger(MQL_TESTER)!=0 ||
          AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO))
        {
         MqlTick diagnostic_tick={};
         double spread_points=-1.0;
         if(SymbolInfoTick(_Symbol,diagnostic_tick) && _Point>0.0 &&
            diagnostic_tick.ask>diagnostic_tick.bid)
            spread_points=(diagnostic_tick.ask-diagnostic_tick.bid)/_Point;
         PrintFormat("QTS ENTRY AUDIT bar=%s timeframe=%d style=%d equity=%.2f minlot=%.2f spread_points=%.1f reason=%s",
                     TimeToString(closed,TIME_DATE|TIME_MINUTES),(int)SignalTimeframe,
                     (int)EntryStyle,AccountInfoDouble(ACCOUNT_EQUITY),
                     SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN),spread_points,status_text);
        }
     }
   else if(last_closed_bar==0)
      last_closed_bar=closed;
   DisplayStatus();
  }
//+------------------------------------------------------------------+
