// QTS Structural Research — only included by QTS_Gold_Robot.mq5.
// Two-bar closed-candle causal signals. No standalone Expert Advisor.
// All trading permissions, sizing and execution remain in the parent EA.

int CompletedStructureSignal(double &atr_value,double &level,double &anchor)
  {
   atr_value=0.0;
   level=0.0;
   anchor=0.0;
   double atr[1];
   if(BarsCalculated(atr_handle)<AtrPeriod+EntrySwingLookbackBars+3 ||
      CopyBuffer(atr_handle,0,1,1,atr)!=1 ||
      !MathIsValidNumber(atr[0]) || atr[0]<=0.0)
     {
      status_text="STRUCTURE: closed ATR not ready";
      return 0;
     }
   // start=1 only completed bars; physical array from oldest to newest.
   int n=EntrySwingLookbackBars+2;
   MqlRates bars[];
   if(CopyRates(_Symbol,SignalTimeframe,1,n,bars)!=n)
     {
      status_text="STRUCTURE: missing closed candles";
      return 0;
     }
   int frame=PeriodSeconds(SignalTimeframe);
   if(frame<=0) return 0;
   double high=0.0,low=DBL_MAX;
   for(int i=0;i<n;i++)
     {
      if(bars[i].low<=0.0 || bars[i].high<bars[i].low ||
         (i>0 && bars[i].time-bars[i-1].time!=frame))
        {
         status_text="STRUCTURE: corrupt/gapped history";
         return 0;
        }
      // The last two candles are probe+confirmation, not prior structure.
      if(i<n-2)
        {
         high=MathMax(high,bars[i].high);
         low=MathMin(low,bars[i].low);
        }
     }
   MqlRates probe=bars[n-2];
   MqlRates confirm=bars[n-1];
   double buffer=atr[0]*StructureBreakConfirmAtr;
   double window=atr[0]*StructureRetestWindowAtr;
   int side=0;
   if(evaluated_style==QTS_BREAK_ACCEPT_RETEST)
     {
      if(probe.open<=high && probe.close>high+buffer &&
         confirm.low>=high-window && confirm.low<=high+window &&
         confirm.close>high+buffer && confirm.close>confirm.open)
        {
         side=1; level=high; anchor=MathMin(confirm.low,high);
        }
      else if(probe.open>=low && probe.close<low-buffer &&
              confirm.high>=low-window && confirm.high<=low+window &&
              confirm.close<low-buffer && confirm.close<confirm.open)
        {
         side=-1; level=low; anchor=MathMax(confirm.high,low);
        }
     }
   else if(evaluated_style==QTS_SWEEP_RECLAIM)
     {
      // CAUTION: previous sweep strategy FAILED on unseen historical ticks.
      // This is NOT validated; no non-tester orders are ever authorized.
      if(probe.low<low-buffer && probe.close>low+buffer &&
         confirm.low>=low-window && confirm.close>low+buffer &&
         confirm.close>confirm.open)
        {
         side=1; level=low; anchor=MathMin(probe.low,confirm.low);
        }
      else if(probe.high>high+buffer && probe.close<high-buffer &&
              confirm.high<=high+window && confirm.close<high-buffer &&
              confirm.close<confirm.open)
        {
         side=-1; level=high; anchor=MathMax(probe.high,confirm.high);
        }
     }
   if(side==0)
     {
      status_text="STRUCTURE: no two-bar break/reclaim and hold";
      return 0;
     }
   if(EnableH1TrendFilter)
     {
      double ma[1],h1_close[1];
      if(h1_handle==INVALID_HANDLE ||
         CopyBuffer(h1_handle,0,1,1,ma)!=1 ||
         BarsCalculated(h1_handle)<55 ||
         CopyClose(_Symbol,PERIOD_H1,1,1,h1_close)!=1 ||
         iTime(_Symbol,PERIOD_H1,0)-iTime(_Symbol,PERIOD_H1,1)!=3600 ||
         !MathIsValidNumber(ma[0]) || !MathIsValidNumber(h1_close[0]) ||
         (side>0 && h1_close[0]<=ma[0]) ||
         (side<0 && h1_close[0]>=ma[0]))
        {
         status_text="STRUCTURE: H1 closed trend veto";
         return 0;
        }
     }
   atr_value=atr[0];
   status_text=StringFormat("STRUCTURE: %s confirmed level %.5f",
                            side>0 ? "BUY":"SELL",level);
   return side;
  }

// Passive LIMIT following causal confirmation; no market-entry chase.
// Stop behind retest/sweep invalidation; broker and fee vetoes apply in EA.
bool PrepareStructureLimit(const int side,const MqlTick &tick,const double atr,
                           const double level,const double anchor,
                           double &price,double &stop,double &target)
  {
   if(side==0 || atr<=0.0 || level<=0.0 || anchor<=0.0)
      return false;
   double step=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(step<=0.0 || _Point<=0.0 || tick.ask<=tick.bid)
      return false;
   double spread=tick.ask-tick.bid;
   double broker_gap=((double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)+2.0)*_Point;
   double min_pending=MathMax(broker_gap,2.0*step);
   double buffer=MathMax(atr*StructuralStopBufferAtr,
                         spread*MinimumStopSpreadMultiple);
   double risk_floor=MathMax(atr*MinimumStopDistanceAtr,
                            MathMax(spread*MinimumStopSpreadMultiple,broker_gap+2.0*step));
   double offset=atr*StructureEntryOffsetAtr;
   if(side>0)
     {
      price=NormalizeDouble(MathFloor((level+offset)/step)*step,_Digits);
      stop=NormalizeDouble(MathFloor((MathMin(anchor,level)-buffer)/step)*step,_Digits);
      if(price<=0.0 || stop<=0.0 || price<=stop ||
         tick.bid-price<min_pending || tick.ask-price>MaxPendingDistanceAtr*atr ||
         price-stop<risk_floor-step*0.51)
         return false;
      target=NormalizeDouble(MathCeil((price+(price-stop)*RewardToRisk)/step)*step,_Digits);
      if(target<=price+broker_gap) return false;
     }
   else
     {
      price=NormalizeDouble(MathCeil((level-offset)/step)*step,_Digits);
      stop=NormalizeDouble(MathCeil((MathMax(anchor,level)+buffer)/step)*step,_Digits);
      if(price<=0.0 || stop<=price ||
         price-tick.ask<min_pending || price-tick.bid>MaxPendingDistanceAtr*atr ||
         stop-price<risk_floor-step*0.51)
         return false;
      target=NormalizeDouble(MathFloor((price-(stop-price)*RewardToRisk)/step)*step,_Digits);
      if(target<=0.0 || price-target<broker_gap)
         return false;
     }
   return MathIsValidNumber(price) && MathIsValidNumber(stop) &&
          MathIsValidNumber(target);
  }
