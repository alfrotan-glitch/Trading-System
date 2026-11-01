// QTS Gold V4: genuinely per-opportunity multi-strategy adaptive router.
// New frozen research hypothesis: TESTER ONLY, OFF by default, never LIVE.
// Each completed M15 bar recomputes market regime and independently checks
// strategy families 0..6 and SMC 8; style 7 is router, not a candidate.
// M1 style 9 is deliberately NOT M15 compatible: no disguised M1 execution.
// No model fitted to the realised trade result; all data are closed bars.
// A candidate rejected by context/cost/risk does NOT hide another candidate.
// Price, SL, TP and broker lot preflight are based on ONE chosen strategy.
#define QTS_V4_MIN_NET_RR 1.25


#define QTS_V4_DECISIONS 10
#define QTS_V4_BAR_GATES 20
int g_v4_diagnostic_candidates[9][QTS_V4_DECISIONS];
int g_v4_diagnostic_gates[QTS_V4_BAR_GATES];

string V4DecisionName(const int n)
  {
   string names[]={"REJECT_SIGNAL","REJECT_LIMIT","REJECT_GEOMETRY",
      "REJECT_SIZE","REJECT_MARKET_CONTEXT","REJECT_COST","REJECT_RR",
      "REJECT_TRANSITION","REJECT_SCORE","ELIGIBLE"};
   if(n<0 || n>=ArraySize(names)) return "UNKNOWN";
   return names[n];
  }
void V4CountCandidate(const int style,const string decision)
  {
   if(MQLInfoInteger(MQL_TESTER)==0 || EntryStyle!=QTS_ADAPTIVE_ROUTER ||
      !TesterUseAdaptiveRouterV4 || style<0 || style>8) return;
   for(int j=0;j<QTS_V4_DECISIONS;j++)
      if(decision==V4DecisionName(j))
        {
         g_v4_diagnostic_candidates[style][j]++;
         return;
        }
  }
// Exactly one CLOSED-BAR decision is counted after ConsiderNewEntry.
// The long-form QTS ENTRY AUDIT remains the detailed broker-time evidence.
string V4GateName(const int n)
  {
   string names[]={"TOTAL_CLOSED_BARS","NO_ELIGIBLE_SETUP",
      "REGIME_WARMUP","REGIME_UNAVAILABLE","VOLATILITY_VETO",
      "RESEARCH_CONFIGURATION_VETO","FROZEN_V5_VETO",
      "OUTSIDE_BROKER_SESSION","RISK_OR_INCIDENT_VETO",
      "QUOTE_OR_SPREAD_VETO","EXISTING_ORDER_OR_POSITION",
      "ENTRY_MUTEX_VETO","FINAL_V3_CONTEXT_VETO",
      "BROKER_ORDER_CHECK_VETO","LOT_LIMIT_OR_COST_VETO",
      "PENDING_ORDER_ACCEPTED","PENDING_ORDER_REJECTED",
      "FINAL_EXECUTION_VETO","PRICE_OR_EXPIRY_VETO",
      "OTHER_NO_SUBMISSION"};
   if(n<0 || n>=ArraySize(names)) return "UNKNOWN";
   return names[n];
  }
void V4RecordClosedBarDecision(const string reason)
  {
   if(MQLInfoInteger(MQL_TESTER)==0 || EntryStyle!=QTS_ADAPTIVE_ROUTER ||
      !TesterUseAdaptiveRouterV4) return;
   g_v4_diagnostic_gates[0]++;
   int category=19;
   if(StringFind(reason,"V4: NO_TRADE")==0) category=1;
   else if(StringFind(reason,"V4: regime has not persisted")==0) category=2;
   else if(StringFind(reason,"V4: missing closed-bar regime")==0) category=3;
   else if(StringFind(reason,"V4: ATR percentile")==0) category=4;
   else if(StringFind(reason,"V4: requires M15")==0 ||
           StringFind(reason,"Research gate:")==0 ||
           StringFind(reason,"ENTRY: disabled")==0 ||
           StringFind(reason,"ENTRY: operator pause")==0) category=5;
   else if(StringFind(reason,"QTS V5 PREREGISTERED_VETO")==0) category=6;
   else if(StringFind(reason,"ENTRY: outside broker session")==0) category=7;
   else if(StringFind(reason,"Quote, spread")==0 ||
           StringFind(reason,"Spread too large")==0) category=9;
   else if(StringFind(reason,"Another chart/strategy")==0) category=10;
   else if(StringFind(reason,"Another EA has the entry lock")==0) category=11;
   else if(StringFind(reason,"V3 MARKET CONTEXT")==0) category=12;
   else if(StringFind(reason,"Broker preflight")==0) category=13;
   else if(StringFind(reason,"SIZE:")==0 ||
           StringFind(reason,"MARGIN:")==0 ||
           StringFind(reason,"TP reward")==0 ||
           StringFind(reason,"Pending-order daily")==0) category=14;
   else if(StringFind(reason,"LIMIT submission accepted")==0) category=15;
   else if(StringFind(reason,"Broker rejected setup")==0) category=16;
   else if(StringFind(reason,"Final execution/risk guard")==0) category=17;
   else if(StringFind(reason,"Price reached limit")==0 ||
           StringFind(reason,"Broker has no safe server")==0) category=18;
   else if(StringFind(reason,"risk",0)>=0 ||
           StringFind(reason,"Risk",0)>=0 ||
           StringFind(reason,"Execution incident")==0 ||
           StringFind(reason,"halt",0)>=0 ||
           StringFind(reason,"Daily trade count")==0) category=8;
   g_v4_diagnostic_gates[category]++;
  }
// Native tester's own CSV survives even when all trade signals are vetoed.
// No order credentials, chart objects, broker account IDs or position data.
bool V4ExportDiagnostics()
  {
   if(MQLInfoInteger(MQL_TESTER)==0 || EntryStyle!=QTS_ADAPTIVE_ROUTER ||
      !TesterUseAdaptiveRouterV4) return true;
   string filename=StringFormat("QTS_V4_DIAGNOSTICS_STYLE_%d_%I64u.csv",
                                (int)EntryStyle,GetTickCount64());
   int file=FileOpen(filename,FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,';');
   if(file==INVALID_HANDLE)
     {
      PrintFormat("QTS V4 DIAGNOSTIC EXPORT ERROR=%d",GetLastError());
      return false;
     }
   FileWrite(file,"scope","style","verdict","count");
   for(int i=0;i<QTS_V4_BAR_GATES;i++)
      FileWrite(file,"CLOSED_BAR",-1,V4GateName(i),g_v4_diagnostic_gates[i]);
   for(int style=0;style<=8;style++)
     {
      if(style==QTS_ADAPTIVE_ROUTER) continue;
      for(int decision=0;decision<QTS_V4_DECISIONS;decision++)
         FileWrite(file,"CANDIDATE",style,V4DecisionName(decision),
                   g_v4_diagnostic_candidates[style][decision]);
     }
   FileFlush(file);
   FileClose(file);
   PrintFormat("QTS V4 DIAGNOSTICS EXPORTED bar_evaluations=%d file=%s",
               g_v4_diagnostic_gates[0],filename);
   return true;
  }

int V4RegimePriority(const int regime,const int style)
  {
   if(style==QTS_SMC_FVG_OB)
      return regime==2 ? 4 : (regime==1 ? 4 : 0);
   // Keep the original per-regime candidate eligibility as a baseline prior.
   return AdaptivePriority(regime,style);
  }

void V4LogCandidate(const int regime,const int style,const string decision,
                    const string details)
  {
   V4CountCandidate(style,decision);
   if(EnableEntryDiagnostics && MQLInfoInteger(MQL_TESTER)!=0)
      PrintFormat("QTS V4 CANDIDATE regime=%d style=%d verdict=%s details=%s",
                  regime,style,decision,details);
  }

bool SelectAdaptiveCandidateV4(const MqlTick &quote,
                               int &side,double &atr,double &level,double &anchor,
                               double &price,double &stop,double &target,
                               int &chosen_style)
  {
   side=0;atr=0;level=0;anchor=0;price=0;stop=0;target=0;
   chosen_style=-1;
   if(!TesterUseAdaptiveRouterV4 || !TesterUseMarketContextV3 ||
      MQLInfoInteger(MQL_TESTER)==0 || EntryStyle!=QTS_ADAPTIVE_ROUTER ||
      SignalTimeframe!=PERIOD_M15)
     {
      status_text="V4: requires M15 adaptive Strategy Tester and V3 filter";
      return false;
     }
   double adx=0.0,ema_gap=0.0;
   const int raw_regime=AdaptiveRegime(adx,ema_gap);
   if(raw_regime<0)
     {
      status_text="V4: missing closed-bar regime evidence";
      return false;
     }
   const int regime=ConfirmedRouterRegime(raw_regime);
   if(regime<0)
     {
      status_text="V4: regime has not persisted for three closed bars";
      return false;
     }
   if(!RouterVolatilityGuardPass())
     {
      status_text="V4: ATR percentile volatility guard abstains";
      return false;
     }
   double best_score=-DBL_MAX;
   int evaluated=0,eligible=0,approved=0;
   string last_rejection="";
   for(int style=0;style<=QTS_SMC_FVG_OB;style++)
     {
      if(style==QTS_ADAPTIVE_ROUTER)
         continue;
      const int priority=V4RegimePriority(regime,style);
      if(priority<=0)
         continue;
      evaluated++;
      evaluated_style=style;
      double a=0.0,l=0.0,an=0.0,p=0.0,sl=0.0,tp=0.0;
      int signal=0;
      if(style==QTS_SMC_FVG_OB)
         signal=CompletedSmcSignal(a,l,an);
      else if(style>=QTS_TREND_IMPULSE)
         signal=CompletedOpportunitySignal(a,l,an);
      else if(style>=QTS_BREAK_ACCEPT_RETEST)
         signal=CompletedStructureSignal(a,l,an);
      else
         signal=CompletedBarSignal(a);
      if(signal==0 || a<=0.0)
        {
         last_rejection=status_text;
         V4LogCandidate(regime,style,"REJECT_SIGNAL",last_rejection);
         continue;
        }
      bool prepared=false;
      if(style==QTS_SMC_FVG_OB)
         prepared=PrepareSmcLimit(signal,quote,a,l,an,p,sl,tp);
      else if(style>=QTS_TREND_IMPULSE)
         prepared=PrepareOpportunityLimit(signal,quote,a,l,an,p,sl,tp);
      else if(style>=QTS_BREAK_ACCEPT_RETEST)
         prepared=PrepareStructureLimit(signal,quote,a,l,an,p,sl,tp);
      else if(style==QTS_RETEST_LIMIT)
         prepared=PrepareRetestLimit(signal,quote,a,p,sl,tp);
      else
         prepared=PreparePullbackLimit(signal,quote,a,p,sl,tp);
      if(!prepared || p<=0.0 || sl<=0.0 || tp<=0.0)
        {
         last_rejection="limit entry geometry, target or broker gap rejected";
         V4LogCandidate(regime,style,"REJECT_LIMIT",last_rejection);
         continue;
        }
      const double distance=MathAbs(p-sl);
      const double reward=MathAbs(tp-p);
      if(!MathIsValidNumber(distance) || !MathIsValidNumber(reward) ||
         distance<=0.0 || reward<=0.0 ||
         (signal>0 && !(sl<p && p<tp)) ||
         (signal<0 && !(tp<p && p<sl)))
        {
         last_rejection="invalid closed-bar stop/target direction";
         V4LogCandidate(regime,style,"REJECT_GEOMETRY",last_rejection);
         continue;
        }
      double lots=SizedLots(signal,p,sl);
      if(lots<=0.0)
        {
         last_rejection="minimum lot, equity risk or broker margin refused";
         V4LogCandidate(regime,style,"REJECT_SIZE",last_rejection);
         continue;
        }
      // V3 is mandatory for V4: a strategy must match the H1, M15 and M5
      // context and prior price structure before it can be scored.
      if(!TesterMarketContextV3(signal,style,quote,a,p,sl,tp))
        {
         last_rejection=status_text;
         V4LogCandidate(regime,style,"REJECT_MARKET_CONTEXT",last_rejection);
         continue;
        }
      ENUM_ORDER_TYPE type=signal>0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      double gross_profit=0.0;
      if(!OrderCalcProfit(type,_Symbol,lots,p,tp,gross_profit) ||
         !MathIsValidNumber(gross_profit))
        {
         last_rejection="native broker TP valuation unavailable";
         V4LogCandidate(regime,style,"REJECT_COST",last_rejection);
         continue;
        }
      const double net_target=gross_profit-AssumedRoundTurnFeePerLot*lots;
      const double stressed_loss=EstimatedMonetaryLoss(signal,lots,p,sl);
      if(stressed_loss<=0.0 || !MathIsValidNumber(net_target) ||
         net_target<=0.0)
        {
         last_rejection="after-cost target or stop cannot be valued";
         V4LogCandidate(regime,style,"REJECT_COST",last_rejection);
         continue;
        }
      const double net_rr=net_target/stressed_loss;
      if(net_rr<QTS_V4_MIN_NET_RR)
        {
         last_rejection=StringFormat("after-cost reward/risk %.3f below %.2f",
                                     net_rr,QTS_V4_MIN_NET_RR);
         V4LogCandidate(regime,style,"REJECT_RR",last_rejection);
         continue;
        }
      if(regime==1 && priority<ROUTER_TRANSITION_MIN_PRIORITY)
        {
         last_rejection="unconfirmed transition regime";
         V4LogCandidate(regime,style,"REJECT_TRANSITION",last_rejection);
         continue;
        }
      eligible++;
      // Frozen heuristic, NOT a calibrated win probability or profit forecast.
      // Reward/risk is measured in broker account currency after cost stress.
      // Priority is regime fit; near-term quote distance and spread penalise
      // unfilled/faraway setups. No realised PnL enters this calculation.
      const double mid=(quote.ask+quote.bid)/2.0;
      const double distance_atr=MathAbs(mid-p)/a;
      const double spread_risk=(quote.ask-quote.bid)/distance;
      const double score=0.50*MathMin(net_rr,3.0)+0.20*(double)priority
                        -0.20*distance_atr-0.30*spread_risk;
      if(!MathIsValidNumber(score))
        {
         last_rejection="nonfinite candidate score";
         V4LogCandidate(regime,style,"REJECT_SCORE",last_rejection);
         continue;
        }
      approved++;
      V4LogCandidate(regime,style,"ELIGIBLE",
                     StringFormat("side=%d netRR=%.3f score=%.4f lots=%.2f entry=%.5f sl=%.5f tp=%.5f",
                                  signal,net_rr,score,lots,p,sl,tp));
      // Deterministic tie-break: lower strategy ID wins equal scores.
      if(score>best_score+1e-9)
        {
         best_score=score;
         chosen_style=style;
         side=signal;atr=a;level=l;anchor=an;
         price=p;stop=sl;target=tp;
        }
     }
   if(chosen_style<0)
     {
      evaluated_style=(int)EntryStyle;
      status_text=StringFormat("V4: NO_TRADE regime=%d ADX=%.2f evaluated=%d eligible=%d last=%s",
                               regime,adx,evaluated,eligible,last_rejection);
      if(EnableEntryDiagnostics)
         Print(status_text);
      return false;
     }
   evaluated_style=chosen_style;
   // V5 challenger ONLY: veto exactly the selected V4 setup when the
   // preregistered style and closed-bar regime agree. No alternate search,
   // stop widening, risk increase or hindsight signal substitution.
   // The unmodified V4 champion still selects the exact same candidate.
   if(TesterUsePreregisteredVetoV5 &&
      chosen_style==TesterVetoStyleV5 && regime==TesterVetoRegimeV5)
     {
      status_text=StringFormat("QTS V5 PREREGISTERED_VETO chosen=%d regime=%d bar=%s",
                               chosen_style,regime,
                               TimeToString(iTime(_Symbol,PERIOD_M15,1),TIME_DATE|TIME_MINUTES));
      if(EnableEntryDiagnostics) Print(status_text);
      evaluated_style=(int)EntryStyle;
      side=0;atr=0;level=0;anchor=0;price=0;stop=0;target=0;
      chosen_style=-1;
      return false;
     }
   status_text=StringFormat("V4: selected strategy %d from %d eligible in regime %d",
                            chosen_style,approved,regime);
   if(EnableEntryDiagnostics)
      PrintFormat("QTS V4 ROUTER CHOICE bar=%s regime=%d ADX=%.2f emaGapATR=%.4f reviewed=%d eligible=%d chosen=%d side=%d entry=%.5f sl=%.5f tp=%.5f score=%.4f",
                  TimeToString(iTime(_Symbol,PERIOD_M15,1),TIME_DATE|TIME_MINUTES),
                  regime,adx,ema_gap,evaluated,approved,chosen_style,side,
                  price,stop,target,best_score);
   return true;
  }
