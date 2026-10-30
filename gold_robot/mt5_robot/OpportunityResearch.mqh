// QTS Gold: three additional closed-bar research hypotheses (evaluated_style 4-6).
// Research only: the parent EA forbids these modes outside Strategy Tester.
// Input parameters are fixed before observing strategy results; not optimized.

int CompletedOpportunitySignal(double &atr_value,double &level,double &anchor)
  {
   atr_value=0.0; level=0.0; anchor=0.0;
   if(BarsCalculated(atr_handle)<AtrPeriod+EntrySwingLookbackBars+4 ||
      BarsCalculated(fast_handle)<SlowEmaPeriod+3 ||
      BarsCalculated(slow_handle)<SlowEmaPeriod+3)
     {
      status_text="OPPORTUNITY: indicators not ready";
      return 0;
     }
   double atr[1],fast[2],slow[2];
   if(CopyBuffer(atr_handle,0,1,1,atr)!=1 ||
      CopyBuffer(fast_handle,0,1,2,fast)!=2 ||
      CopyBuffer(slow_handle,0,1,2,slow)!=2 ||
      !MathIsValidNumber(atr[0]) || atr[0]<=0.0 ||
      !MathIsValidNumber(fast[1]) || !MathIsValidNumber(slow[1]))
     {
      status_text="OPPORTUNITY: closed indicator values unavailable";
      return 0;
     }
   int n=EntrySwingLookbackBars+2;
   MqlRates bars[];
   if(CopyRates(_Symbol,SignalTimeframe,1,n,bars)!=n)
     {
      status_text="OPPORTUNITY: insufficient closed bars";
      return 0;
     }
   int frame=PeriodSeconds(SignalTimeframe);
   if(frame<=0) return 0;
   for(int i=0;i<n;i++)
     {
      if(bars[i].low<=0.0 || bars[i].high<bars[i].low ||
         (i>0 && bars[i].time-bars[i-1].time!=frame))
        {
         status_text="OPPORTUNITY: stale, gapped or invalid bars";
         return 0;
        }
     }
   double vol=atr[0];
   MqlRates last=bars[n-1];
   int side=0;
   if(evaluated_style==QTS_TREND_IMPULSE)
     {
      // Trend continuation without the strict EMA CROSS used by Style 1.
      // One convincing completed impulse; next entry is a passive retrace.
      double body=last.close-last.open;
      if(fast[1]>slow[1] && last.close>fast[1]+0.10*vol &&
         body>=0.35*vol && last.close>bars[n-2].close+0.12*vol)
        {
         side=1; level=last.high; anchor=last.low;
        }
      else if(fast[1]<slow[1] && last.close<fast[1]-0.10*vol &&
              -body>=0.35*vol && last.close<bars[n-2].close-0.12*vol)
        {
         side=-1; level=last.low; anchor=last.high;
        }
     }
   else if(evaluated_style==QTS_RANGE_REJECTION)
     {
      // Mean-reversion at an established prior range edge.
      // Last candle is NOT part of the range used to generate its signal.
      double high=0.0,low=DBL_MAX;
      for(int i=0;i<n-1;i++)
        {
         high=MathMax(high,bars[i].high);
         low=MathMin(low,bars[i].low);
        }
      double width=high-low;
      double body=MathAbs(last.close-last.open);
      double lower_wick=MathMin(last.open,last.close)-last.low;
      double upper_wick=last.high-MathMax(last.open,last.close);
      if(width>=0.9*vol && width<=4.0*vol)
        {
         if(last.low<=low+0.15*vol && last.close>last.open &&
            lower_wick>=MathMax(0.20*vol,body*1.20) &&
            last.close>=low+0.35*vol && last.close<high)
           {
            side=1; level=high; anchor=low;
           }
         else if(last.high>=high-0.15*vol && last.close<last.open &&
                 upper_wick>=MathMax(0.20*vol,body*1.20) &&
                 last.close<=high-0.35*vol && last.close>low)
           {
            side=-1; level=low; anchor=high;
           }
        }
     }
   else if(evaluated_style==QTS_INSIDE_BREAKOUT)
     {
      // Three completed candles: mother, inside, breakout.
      MqlRates mother=bars[n-3];
      MqlRates inside=bars[n-2];
      bool contained=inside.high<mother.high && inside.low>mother.low &&
                     mother.high-mother.low>=0.65*vol;
      if(contained && fast[1]>slow[1] &&
         last.close>mother.high+0.10*vol &&
         last.close-last.open>=0.25*vol)
        {
         side=1; level=mother.high; anchor=inside.low;
        }
      else if(contained && fast[1]<slow[1] &&
              last.close<mother.low-0.10*vol &&
              last.open-last.close>=0.25*vol)
        {
         side=-1; level=mother.low; anchor=inside.high;
        }
     }
   if(side==0)
     {
      status_text="OPPORTUNITY: no completed impulse, range rejection or inside break";
      return 0;
     }
   if(EnableH1TrendFilter && evaluated_style!=QTS_RANGE_REJECTION)
     {
      double h1ma[1],h1close[1];
      datetime h0=iTime(_Symbol,PERIOD_H1,0);
      datetime h1=iTime(_Symbol,PERIOD_H1,1);
      if(h1_handle==INVALID_HANDLE || BarsCalculated(h1_handle)<55 ||
         CopyBuffer(h1_handle,0,1,1,h1ma)!=1 ||
         CopyClose(_Symbol,PERIOD_H1,1,1,h1close)!=1 ||
         h0<=0 || h1<=0 || h0-h1!=3600 ||
         !MathIsValidNumber(h1ma[0]) || !MathIsValidNumber(h1close[0]) ||
         (side>0 && h1close[0]<=h1ma[0]) ||
         (side<0 && h1close[0]>=h1ma[0]))
        {
         status_text="OPPORTUNITY: closed H1 trend veto";
         return 0;
        }
     }
   atr_value=vol;
   status_text=StringFormat("OPPORTUNITY: style=%d %s closed-bar candidate",
                            (int)evaluated_style,side>0 ? "BUY":"SELL");
   return side;
  }

// The shared broker size, fee, margin, expiration and permission checks
// remain in the parent EA. Never switch to market orders for more fills.
bool PrepareOpportunityLimit(const int side,const MqlTick &tick,const double atr,
                             const double level,const double anchor,
                             double &price,double &stop,double &target)
  {
   if(side==0 || atr<=0.0 || anchor<=0.0 || level<=0.0 ||
      tick.ask<=tick.bid || _Point<=0.0)
      return false;
   double step=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(step<=0.0) return false;
   double spread=tick.ask-tick.bid;
   double broker_gap=((double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)+2.0)*_Point;
   double pending_gap=MathMax(broker_gap,2.0*step);
   double buffer=MathMax(atr*StructuralStopBufferAtr,spread*MinimumStopSpreadMultiple);
   double floor_gap=MathMax(atr*MinimumStopDistanceAtr,
                     MathMax(spread*MinimumStopSpreadMultiple,broker_gap+2.0*step));
   double desired=0.0;
   if(evaluated_style==QTS_TREND_IMPULSE)
      desired=side>0 ? tick.bid-0.25*atr : tick.ask+0.25*atr;
   else if(evaluated_style==QTS_RANGE_REJECTION)
      desired=side>0 ? anchor+0.25*atr : anchor-0.25*atr;
   else if(evaluated_style==QTS_INSIDE_BREAKOUT)
      desired=side>0 ? level-0.03*atr : level+0.03*atr;
   else
      return false;
   if(side>0)
     {
      price=NormalizeDouble(MathFloor(desired/step)*step,_Digits);
      stop=NormalizeDouble(MathFloor((MathMin(anchor,price-floor_gap)-buffer)/step)*step,_Digits);
      if(price<=0.0 || stop<=0.0 || price<=stop ||
         tick.bid-price<pending_gap ||
         tick.ask-price>MaxPendingDistanceAtr*atr ||
         price-stop<floor_gap-step*0.51)
         return false;
      target=NormalizeDouble(MathCeil((price+(price-stop)*RewardToRisk)/step)*step,_Digits);
      if(evaluated_style==QTS_RANGE_REJECTION && target>level-spread)
         return false;
      if(target-price<broker_gap) return false;
     }
   else
     {
      price=NormalizeDouble(MathCeil(desired/step)*step,_Digits);
      stop=NormalizeDouble(MathCeil((MathMax(anchor,price+floor_gap)+buffer)/step)*step,_Digits);
      if(price<=0.0 || stop<=price || price-tick.ask<pending_gap ||
         price-tick.bid>MaxPendingDistanceAtr*atr ||
         stop-price<floor_gap-step*0.51)
         return false;
      target=NormalizeDouble(MathFloor((price-(stop-price)*RewardToRisk)/step)*step,_Digits);
      if(evaluated_style==QTS_RANGE_REJECTION && target<level+spread)
         return false;
      if(target<=0.0 || price-target<broker_gap) return false;
     }
   return MathIsValidNumber(price) && MathIsValidNumber(stop) &&
          MathIsValidNumber(target);
  }
