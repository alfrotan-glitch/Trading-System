// QTS GOLD test-only Retest + Sweep dual strategy challenger (OFF by default).
// Each M15 closed bar evaluates both strategy candidates independently.
// A single shared broker/risk book is kept. No overlapping positions, no
// simultaneous conflicting pending orders and no autonomous live trading.
// Research modes: 1 both directions each; 2 BUY Retest, SELL Sweep (post-hoc).
// Research observation only. These variables are assigned by the frozen
// router; they do not affect eligibility, stop placement, sizing or orders.
int qts_dual_router_eligible=-1;
string qts_dual_router_verdict="NOT_EVALUATED";

bool SelectDualResearchCandidate(const MqlTick &quote,
                                 int &side,double &atr,double &level,double &anchor,
                                 double &price,double &stop,double &target,
                                 int &chosen_style)
  {
   side=0;atr=0.0;level=0.0;anchor=0.0;price=0.0;stop=0.0;target=0.0;
   chosen_style=-1;
   qts_dual_router_eligible=0;
   qts_dual_router_verdict="CONFIG_REFUSED";
   if(MQLInfoInteger(MQL_TESTER)==0 || EntryStyle!=QTS_ADAPTIVE_ROUTER ||
      SignalTimeframe!=PERIOD_M15 || TesterDualStrategyMode<1 ||
      TesterDualStrategyMode>2 || TesterUseMarketContextV3 ||
      TesterUseAdaptiveRouterV4 || TesterUsePreregisteredVetoV5)
     {
      evaluated_style=(int)EntryStyle;
      status_text="DUAL: tester-only research configuration refused";
      return false;
     }
   qts_dual_router_verdict="EVALUATING";
   int eligible=0;
   for(int i=0;i<2;i++)
     {
      int style=i==0 ? QTS_RETEST_LIMIT : QTS_SWEEP_RECLAIM;
      evaluated_style=style;
      double a=0.0,l=0.0,an=0.0;
      int signal=style==QTS_RETEST_LIMIT ?
                 CompletedBarSignal(a) : CompletedStructureSignal(a,l,an);
      if(signal==0 || a<=0.0)
        {
         if(EnableEntryDiagnostics)
            PrintFormat("QTS DUAL CANDIDATE style=%d verdict=NO_SIGNAL reason=%s",style,status_text);
         continue;
        }
      if(TesterDualStrategyMode==2 &&
         ((style==QTS_RETEST_LIMIT && signal<0) ||
          (style==QTS_SWEEP_RECLAIM && signal>0)))
        {
         if(EnableEntryDiagnostics)
            PrintFormat("QTS DUAL CANDIDATE style=%d side=%d verdict=DIRECTION_VETO",style,signal);
         continue;
        }
      double p=0.0,sl=0.0,tp=0.0;
      bool prepared=style==QTS_RETEST_LIMIT ?
          PrepareRetestLimit(signal,quote,a,p,sl,tp) :
          PrepareStructureLimit(signal,quote,a,l,an,p,sl,tp);
      if(!prepared || p<=0.0 || sl<=0.0 || tp<=0.0 ||
         !MathIsValidNumber(p) || !MathIsValidNumber(sl) ||
         !MathIsValidNumber(tp) ||
         (signal>0 && !(sl<p && p<tp)) ||
         (signal<0 && !(tp<p && p<sl)) ||
         SizedLots(signal,p,sl)<=0.0)
        {
         if(EnableEntryDiagnostics)
            PrintFormat("QTS DUAL CANDIDATE style=%d side=%d verdict=LIMIT_OR_BROKER_RISK_VETO",style,signal);
         continue;
        }
      eligible++;
      if(EnableEntryDiagnostics)
         PrintFormat("QTS DUAL CANDIDATE style=%d side=%d verdict=ELIGIBLE limit=%.5f sl=%.5f tp=%.5f",
                     style,signal,p,sl,tp);
      if(eligible==1)
        {
         chosen_style=style;side=signal;atr=a;level=l;anchor=an;
         price=p;stop=sl;target=tp;
        }
     }
   qts_dual_router_eligible=eligible;
   qts_dual_router_verdict=eligible==0 ? "NO_EXECUTABLE" :
                          (eligible>1 ? "COLLISION_ABSTAIN" : "CANDIDATE_SELECTED");
   if(eligible!=1)
     {
      // Collision abstention is preregistered; never rank by in-sample PnL.
      chosen_style=-1;side=0;atr=0.0;level=0.0;anchor=0.0;
      price=0.0;stop=0.0;target=0.0;
      evaluated_style=(int)EntryStyle;
      status_text=eligible==0 ? "DUAL: no executable closed-bar setup" :
                                "DUAL: collision of eligible candidates; no order";
      if(EnableEntryDiagnostics)
         PrintFormat("QTS DUAL DECISION mode=%d eligible=%d verdict=ABSTAIN",
                     TesterDualStrategyMode,eligible);
      return false;
     }
   evaluated_style=chosen_style;
   status_text=StringFormat("DUAL: mode=%d style=%d side=%d",
                            TesterDualStrategyMode,chosen_style,side);
   if(EnableEntryDiagnostics)
      PrintFormat("QTS DUAL DECISION mode=%d eligible=1 chosen=%d side=%d limit=%.5f sl=%.5f tp=%.5f",
                  TesterDualStrategyMode,chosen_style,side,price,stop,target);
   return true;
  }
