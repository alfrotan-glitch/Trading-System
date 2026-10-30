// QTS SMC research — Style 8 (QTS_SMC_FVG_OB). Strategy Tester ONLY.
// Preregistered 2026-10-30 in gold_robot/docs/PREREGISTRATION_ADAPTIVE_2026-10-30.md.
// Genuine SMC construction, distinct from Styles 0-7:
//  - swing pivots over a fixed closed-bar window (NOT the 8-bar min/max),
//  - a displacement bar breaking a prior swing by >0.10xATR,
//  - an order block = the last opposing candle before that displacement bar,
//  - a fair-value gap = the 3-bar gap around the displacement bar (when present),
//  - mitigation = a later closed bar entering the OB/FVG zone and closing
//    back in trade direction,
//  - confirmation = the last closed bar closing beyond the broken swing
//    (BOS/CHoCH) in trade direction.
// Entry is ONLY on a future limit at the zone edge, after that confirmation.
// Never on a sweep alone, never on an unconfirmed mitigation, never on a
// current (unclosed) bar. All permissions, sizing, expiry, session and
// broker preflight remain in the parent EA. UNVALIDATED, UNCOMPILED on
// Linux (no MetaEditor/MT5) — Windows MetaEditor must pass before any use.
// Frozen window: 20 closed bars, indices fixed below. Changing any
// threshold here restarts the unseen-window clock.
#define SMC_WINDOW_BARS 20
#define SMC_PRIOR_BARS 12
#define SMC_DISPLACEMENT_INDEX 12
#define SMC_FVG_BEFORE_INDEX 11
#define SMC_FVG_AFTER_INDEX 13
#define SMC_CONFIRM_INDEX 19

int CompletedSmcSignal(double &atr_value,double &level,double &anchor)
  {
   atr_value=0.0; level=0.0; anchor=0.0;
   double atr[1];
   if(BarsCalculated(atr_handle)<AtrPeriod+SMC_WINDOW_BARS+3 ||
      CopyBuffer(atr_handle,0,1,1,atr)!=1 ||
      !MathIsValidNumber(atr[0]) || atr[0]<=0.0)
     {
      status_text="SMC: closed ATR not ready";
      return 0;
     }
   MqlRates bars[];
   if(CopyRates(_Symbol,SignalTimeframe,1,SMC_WINDOW_BARS,bars)!=SMC_WINDOW_BARS)
     {
      status_text="SMC: missing closed candles";
      return 0;
     }
   int frame=PeriodSeconds(SignalTimeframe);
   if(frame<=0) return 0;
   for(int i=0;i<SMC_WINDOW_BARS;i++)
     {
      if(bars[i].low<=0.0 || bars[i].high<bars[i].low ||
         (i>0 && bars[i].time-bars[i-1].time!=frame))
        {
         status_text="SMC: corrupt/gapped history";
         return 0;
        }
     }
   double swing_high=0.0,swing_low=DBL_MAX;
   for(int i=0;i<SMC_PRIOR_BARS;i++)
     {
      swing_high=MathMax(swing_high,bars[i].high);
      swing_low=MathMin(swing_low,bars[i].low);
     }
   MqlRates disp=bars[SMC_DISPLACEMENT_INDEX];
   double buffer=atr[0]*0.10;
   int side=0;
   if(disp.close>swing_high+buffer && disp.close>disp.open)
      side=1;
   else if(disp.close<swing_low-buffer && disp.close<disp.open)
      side=-1;
   else
     {
      status_text="SMC: no displacement break of prior swing";
      return 0;
     }
   // Order block: last opposing candle before the displacement bar.
   double ob_low=0.0,ob_high=0.0;
   bool ob_found=false;
   for(int i=SMC_DISPLACEMENT_INDEX-1;i>=0;i--)
     {
      if((side>0 && bars[i].close<bars[i].open) ||
         (side<0 && bars[i].close>bars[i].open))
        {
         ob_low=bars[i].low; ob_high=bars[i].high; ob_found=true; break;
        }
     }
   if(!ob_found)
     {
      status_text="SMC: no order block before displacement";
      return 0;
     }
   // Fair-value gap around the displacement bar, when present. The zone
   // used is the FVG if it exists, otherwise the order block. Both are
   // closed-bar zones; no current-bar data is used.
   double zone_low=ob_low,zone_high=ob_high;
   if(side>0 && bars[SMC_FVG_AFTER_INDEX].low>bars[SMC_FVG_BEFORE_INDEX].high)
     {
      zone_low=bars[SMC_FVG_BEFORE_INDEX].high;
      zone_high=bars[SMC_FVG_AFTER_INDEX].low;
     }
   else if(side<0 && bars[SMC_FVG_AFTER_INDEX].high<bars[SMC_FVG_BEFORE_INDEX].low)
     {
      zone_low=bars[SMC_FVG_AFTER_INDEX].high;
      zone_high=bars[SMC_FVG_BEFORE_INDEX].low;
     }
   if(zone_high<=zone_low)
     {
      status_text="SMC: empty mitigation zone";
      return 0;
     }
   // Mitigation: a closed bar after displacement, before confirmation,
   // that enters the zone and closes back in trade direction.
   bool mitigated=false;
   for(int i=SMC_DISPLACEMENT_INDEX+1;i<SMC_CONFIRM_INDEX;i++)
     {
      if(side>0 && bars[i].low<=zone_high && bars[i].close>=zone_low && bars[i].close>bars[i].open)
         mitigated=true;
      if(side<0 && bars[i].high>=zone_low && bars[i].close<=zone_high && bars[i].close<bars[i].open)
         mitigated=true;
     }
   if(!mitigated)
     {
      status_text="SMC: no closed-bar mitigation into zone";
      return 0;
     }
   // Confirmation: last closed bar closes beyond the broken swing (BOS).
   MqlRates confirm=bars[SMC_CONFIRM_INDEX];
   if(side>0 && !(confirm.close>swing_high && confirm.close>confirm.open))
     {
      status_text="SMC: no BOS confirmation close";
      return 0;
     }
   if(side<0 && !(confirm.close<swing_low && confirm.close<confirm.open))
     {
      status_text="SMC: no BOS confirmation close";
      return 0;
     }
   if(EnableH1TrendFilter)
     {
      double h1ma[1],h1close[1];
      datetime h0=iTime(_Symbol,PERIOD_H1,0);
      datetime h1=iTime(_Symbol,PERIOD_H1,1);
      if(h1_handle==INVALID_HANDLE || BarsCalculated(h1_handle)<55 ||
         CopyBuffer(h1_handle,0,1,1,h1ma)!=1 || CopyClose(_Symbol,PERIOD_H1,1,1,h1close)!=1 ||
         h0<=0 || h1<=0 || h0-h1!=3600 ||
         !MathIsValidNumber(h1ma[0]) || !MathIsValidNumber(h1close[0]) ||
         (side>0 && h1close[0]<=h1ma[0]) || (side<0 && h1close[0]>=h1ma[0]))
        {
         status_text="SMC: H1 closed trend veto";
         return 0;
        }
     }
   // level = zone edge nearest price (the future limit), anchor = zone
   // extreme behind the entry (the stop anchor for PrepareSmcLimit).
   atr_value=atr[0];
   if(side>0)
     {
      level=zone_high; anchor=zone_low;
     }
   else
     {
      level=zone_low; anchor=zone_high;
     }
   status_text=StringFormat("SMC: %s FVG/OB mitigation + BOS, zone %.5f-%.5f",
                           side>0 ? "BUY":"SELL",zone_low,zone_high);
   return side;
  }

// Passive LIMIT at the mitigation zone edge. Same broker/risk pattern as
// PrepareOpportunityLimit: tick rounding, broker gap, floor gap, buffer,
// pending-distance cap, TP = R x risk, broker-gap floor on TP.
bool PrepareSmcLimit(const int side,const MqlTick &tick,const double atr,
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
   if(side>0)
     {
      price=NormalizeDouble(MathFloor(level/step)*step,_Digits);
      stop=NormalizeDouble(MathFloor((MathMin(anchor,price-floor_gap)-buffer)/step)*step,_Digits);
      if(price<=0.0 || stop<=0.0 || price<=stop ||
         tick.bid-price<pending_gap ||
         tick.ask-price>MaxPendingDistanceAtr*atr ||
         price-stop<floor_gap-step*0.51)
         return false;
      target=NormalizeDouble(MathCeil((price+(price-stop)*RewardToRisk)/step)*step,_Digits);
      if(target-price<broker_gap) return false;
     }
   else
     {
      price=NormalizeDouble(MathCeil(level/step)*step,_Digits);
      stop=NormalizeDouble(MathCeil((MathMax(anchor,price+floor_gap)+buffer)/step)*step,_Digits);
      if(price<=0.0 || stop<=price || price-tick.ask<pending_gap ||
         price-tick.bid>MaxPendingDistanceAtr*atr ||
         stop-price<floor_gap-step*0.51)
         return false;
      target=NormalizeDouble(MathFloor((price-(stop-price)*RewardToRisk)/step)*step,_Digits);
      if(target<=0.0 || price-target<broker_gap) return false;
     }
   return MathIsValidNumber(price) && MathIsValidNumber(stop) &&
          MathIsValidNumber(target);
  }
