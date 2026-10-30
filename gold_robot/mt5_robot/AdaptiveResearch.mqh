// QTS Gold adaptive hypothesis router (EntryStyle=7). Strategy Tester ONLY.
// Fixed EX-ANTE rules: every signal, indicator and candle is fully closed.
// These are unvalidated regime heuristics, not a profit forecast or fitted model.
// Never uses broker trade outcomes, future ticks, or previous test results.
int AdaptiveRegime(double &adx,double &ema_gap_atr)
  {
   adx=0.0; ema_gap_atr=0.0;
   double a[1],f[1],s[1],vol[1];
   if(adx_handle==INVALID_HANDLE || fast_handle==INVALID_HANDLE ||
      slow_handle==INVALID_HANDLE || atr_handle==INVALID_HANDLE ||
      CopyBuffer(adx_handle,0,1,1,a)!=1 ||
      CopyBuffer(fast_handle,0,1,1,f)!=1 ||
      CopyBuffer(slow_handle,0,1,1,s)!=1 ||
      CopyBuffer(atr_handle,0,1,1,vol)!=1 ||
      !MathIsValidNumber(a[0]) || !MathIsValidNumber(f[0]) ||
      !MathIsValidNumber(s[0]) || !MathIsValidNumber(vol[0]) ||
      vol[0]<=0.0 || a[0]<0.0 || a[0]>100.0)
      return -1; // Fail closed on unavailable closed-bar context.
   adx=a[0];ema_gap_atr=MathAbs(f[0]-s[0])/vol[0];
   if(adx>=25.0 && ema_gap_atr>=0.12) return 2; // trending
   if(adx<=19.0 || ema_gap_atr<0.07) return 0; // range/compression
   return 1; // transition
  }

// Routing matrix is intentionally fixed; do not tune it on same-period PnL.
// Different regimes may allow multiple candidates, but only ONE may be sent.
// A candidate is still subject to all shared spread, risk, lot, margin,
// expiry, existing exposure and broker preflight checks in the parent EA.
int AdaptivePriority(const int regime,const int style)
  {
   if(regime==2) // trend
     {
      if(style==QTS_RETEST_LIMIT) return 4;
      if(style==QTS_BREAK_ACCEPT_RETEST) return 3;
      if(style==QTS_TREND_IMPULSE) return 3;
      if(style==QTS_INSIDE_BREAKOUT) return 2;
      return 0;
     }
   if(regime==0) // range
     {
      if(style==QTS_SWEEP_RECLAIM) return 4;
      if(style==QTS_RANGE_REJECTION) return 3;
      if(style==QTS_FORMER_STOP_LIMIT) return 2;
      return 0;
     }
   if(regime==1) // transition
     {
      if(style==QTS_RETEST_LIMIT) return 4;
      if(style==QTS_BREAK_ACCEPT_RETEST) return 3;
      if(style==QTS_SWEEP_RECLAIM) return 3;
      if(style==QTS_INSIDE_BREAKOUT) return 2;
     }
   return 0;
  }

bool SelectAdaptiveCandidate(const MqlTick &quote,
                             int &side,double &atr,double &level,double &anchor,
                             double &price,double &stop,double &target,
                             int &chosen_style)
  {
   side=0;atr=0;level=0;anchor=0;price=0;stop=0;target=0;
   chosen_style=-1;
   if(MQLInfoInteger(MQL_TESTER)==0)
     {
      status_text="ROUTER: dynamic strategy selection is Tester-only";
      return false;
     }
   double adx=0.0,ema_gap=0.0;
   int regime=AdaptiveRegime(adx,ema_gap);
   if(regime<0)
     {
      status_text="ROUTER: closed-bar regime unavailable";
      return false;
     }
   double best=-DBL_MAX;
   int accepted=0;
   for(int style=0;style<7;style++)
     {
      int priority=AdaptivePriority(regime,style);
      if(priority==0) continue;
      evaluated_style=style; // All three helpers read this selected family.
      double candidate_atr=0.0, candidate_level=0.0,candidate_anchor=0.0;
      int candidate_side=0;
      if(style>=4)
         candidate_side=CompletedOpportunitySignal(candidate_atr,candidate_level,candidate_anchor);
      else if(style>=2)
         candidate_side=CompletedStructureSignal(candidate_atr,candidate_level,candidate_anchor);
      else
         candidate_side=CompletedBarSignal(candidate_atr);
      if(candidate_side==0 || candidate_atr<=0.0) continue;
      double p=0.0,sl=0.0,tp=0.0;
      bool prepared=false;
      if(style>=4)
         prepared=PrepareOpportunityLimit(candidate_side,quote,candidate_atr,
                                            candidate_level,candidate_anchor,p,sl,tp);
      else if(style>=2)
         prepared=PrepareStructureLimit(candidate_side,quote,candidate_atr,
                                          candidate_level,candidate_anchor,p,sl,tp);
      else if(style==QTS_RETEST_LIMIT)
         prepared=PrepareRetestLimit(candidate_side,quote,candidate_atr,p,sl,tp);
      else
         prepared=PreparePullbackLimit(candidate_side,quote,candidate_atr,p,sl,tp);
      if(!prepared || p<=0.0 || tp<=0.0 || sl<=0.0) continue;
      double risk=MathAbs(p-sl),reward=MathAbs(tp-p);
      if(risk<=0.0 || reward<=0.0 ||
         !MathIsValidNumber(risk) || !MathIsValidNumber(reward))
         continue;
      // An untradeable broker minimum lot cannot win the routing decision.
      if(SizedLots(candidate_side,p,sl)<=0.0) continue;
      accepted++;
      double ratio=MathMin(2.0,reward/risk);
      double relative_spread=(quote.ask-quote.bid)/risk;
      double score=(double)priority+0.20*ratio-0.30*relative_spread;
      if(!MathIsValidNumber(score)) continue;
      if(score>best+1e-9)
        {
         best=score;
         chosen_style=style;side=candidate_side;
         atr=candidate_atr;level=candidate_level;anchor=candidate_anchor;
         price=p;stop=sl;target=tp;
        }
     }
   if(chosen_style<0)
     {
      evaluated_style=(int)EntryStyle;
      status_text=StringFormat("ROUTER: no executable closed-bar setup regime=%d adx=%.1f",
                               regime,adx);
      return false;
     }
   evaluated_style=chosen_style;
   status_text=StringFormat("ROUTER: regime=%d adx=%.1f ema_gap_atr=%.2f eligible=%d selected=%d",
                           regime,adx,ema_gap,accepted,chosen_style);
   if(EnableEntryDiagnostics)
      PrintFormat("QTS ROUTER DECISION time=%s regime=%d adx=%.2f ema_gap_atr=%.4f eligible=%d chosen=%d side=%d entry=%.5f sl=%.5f tp=%.5f score=%.4f",
                  TimeToString(iTime(_Symbol,SignalTimeframe,1),TIME_DATE|TIME_MINUTES),
                  regime,adx,ema_gap,accepted,chosen_style,side,price,stop,target,best);
   return true;
  }
