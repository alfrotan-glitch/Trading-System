// QTS M1 scalp — Style 9 (QTS_M1_SCALP). Strategy Tester ONLY.
// Preregistered 2026-10-30 in gold_robot/docs/PREREGISTRATION_ADAPTIVE_2026-10-30.md
// (scalp numbers added to that document at implementation time, BEFORE any
// scalp PnL evaluation — no scalp return has been viewed).
// Genuine closed-bar M1 signal, ported from src/qts/research/scalp_regimes.py
// (propose_scalp_entry only — NOT the anticipatory/pre-breakout challenger):
//  - 34 closed M1 bars, oldest first. past = bars 1..32, current = bar 33.
//  - efficiency = |past last - past first| / sum(|past steps|), over 31 steps.
//  - volatility = sum(|past steps|) / 31. Width = max(past) - min(past);
//    width must exceed volatility, otherwise no signal.
//  - regime UP if efficiency >= 0.43 and drift > 0; DOWN if >= 0.43 and
//    drift < 0; RANGE if efficiency <= 0.28; else TRANSITION.
//  - UP trend-pullback: past last fell vs previous, current rose back above
//    past last, the pullback depth >= volatility, current below the recent
//    9-bar high. DOWN mirrored.
//  - RANGE fade: current in the bottom/top quartile of past and moving back
//    toward the interior (up from the low quartile, down from the high).
//  - Breakout: UP/TRANSITION current above max(past last 20) + 0.2*volatility;
//    DOWN/TRANSITION mirrored.
// Entry is a future LIMIT at the last closed close (level); it is NOT a
// market order and NOT a relabelled M5 signal. Exit is broker SL/TP in
// basis points (frozen below), plus the shared 15-minute position time
// cap enforced in OnInit for Style 9 (MaxPositionMinutes must equal 15)
// and the shared pending expiry (PendingExpiryBars, default 2 M1 bars).
// Spread is capped by the shared EA gate (MaxSpreadBps, default 3 bps)
// in FreshEntryQuote; no separate scalp spread parameter exists.
// All permissions, sizing, expiry, session and broker preflight remain
// in the parent EA. UNVALIDATED, UNCOMPILED on Linux (no MetaEditor/MT5)
// — Windows MetaEditor must pass before any use. M1 results are
// spread/slippage-sensitive by construction.
// Frozen: changing any threshold here restarts the unseen-window clock.
#define SCALP_BARS 34
#define SCALP_EFF_HIGH 0.43
#define SCALP_EFF_LOW 0.28
#define SCALP_TP_BPS 15.0
#define SCALP_SL_BPS 12.0

int CompletedScalpSignal(double &atr_value,double &level,double &anchor)
  {
   atr_value=0.0; level=0.0; anchor=0.0;
   if(SignalTimeframe!=PERIOD_M1)
     {
      status_text="SCALP: M1 timeframe only";
      return 0;
     }
   double atr[1];
   if(BarsCalculated(atr_handle)<AtrPeriod+SCALP_BARS+3 ||
      CopyBuffer(atr_handle,0,1,1,atr)!=1 ||
      !MathIsValidNumber(atr[0]) || atr[0]<=0.0)
     {
      status_text="SCALP: closed ATR not ready";
      return 0;
     }
   double closes[];
   MqlRates bars[];
   if(CopyClose(_Symbol,SignalTimeframe,1,SCALP_BARS,closes)!=SCALP_BARS ||
      CopyRates(_Symbol,SignalTimeframe,1,SCALP_BARS,bars)!=SCALP_BARS)
     {
      status_text="SCALP: missing closed M1 candles";
      return 0;
     }
   int frame=PeriodSeconds(SignalTimeframe);
   if(frame<=0) return 0;
   for(int i=0;i<SCALP_BARS;i++)
     {
      if(closes[i]<=0.0 || bars[i].low<=0.0 || bars[i].high<bars[i].low ||
         (i>0 && bars[i].time-bars[i-1].time!=frame))
        {
         status_text="SCALP: corrupt/gapped M1 history";
         return 0;
        }
     }
   // past = closes[1..32] (32 bars), current = closes[33].
   double abs_steps=0.0;
   for(int i=2;i<=32;i++)
      abs_steps+=MathAbs(closes[i]-closes[i-1]);
   if(abs_steps<=0.0)
     {
      status_text="SCALP: zero M1 movement";
      return 0;
     }
   double volatility=abs_steps/31.0;
   double efficiency=MathAbs(closes[32]-closes[1])/abs_steps;
   double drift=closes[32]-closes[1];
   double low=closes[1],high=closes[1];
   for(int i=2;i<=32;i++)
     {
      low=MathMin(low,closes[i]);
      high=MathMax(high,closes[i]);
     }
   double width=high-low;
   if(width<=volatility)
     {
      status_text="SCALP: M1 range narrower than mean step";
      return 0;
     }
   int regime=0; // 1=UP, -1=DOWN, 2=RANGE, 0=TRANSITION
   if(efficiency>=SCALP_EFF_HIGH && drift>0.0) regime=1;
   else if(efficiency>=SCALP_EFF_HIGH && drift<0.0) regime=-1;
   else if(efficiency<=SCALP_EFF_LOW) regime=2;
   double current=closes[33];
   double recent_high=closes[24],recent_low=closes[24];
   for(int i=25;i<=32;i++)
     {
      recent_high=MathMax(recent_high,closes[i]);
      recent_low=MathMin(recent_low,closes[i]);
     }
   double past20_high=closes[13],past20_low=closes[13];
   for(int i=14;i<=32;i++)
     {
      past20_high=MathMax(past20_high,closes[i]);
      past20_low=MathMin(past20_low,closes[i]);
     }
   int side=0;
   if(regime==1 && closes[32]<closes[31] && current>closes[32] &&
      recent_high-closes[32]>=volatility && current<recent_high)
      side=1;
   else if(regime==-1 && closes[32]>closes[31] && current<closes[32] &&
           closes[32]-recent_low>=volatility && current>recent_low)
      side=-1;
   else if(regime==2 && low<=current && current<=low+width*0.25 &&
           current>closes[32])
      side=1;
   else if(regime==2 && high-width*0.25<=current && current<=high &&
           current<closes[32])
      side=-1;
   else if((regime==1 || regime==0) && current>past20_high+volatility*0.2)
      side=1;
   else if((regime==-1 || regime==0) && current<past20_low-volatility*0.2)
      side=-1;
   if(side==0)
     {
      status_text="SCALP: no closed-bar M1 scalp setup";
      return 0;
     }
   atr_value=atr[0];
   level=current;
   anchor=current;
   status_text=StringFormat("SCALP: %s M1 efficiency %.2f regime %d",
                           side>0 ? "BUY":"SELL",efficiency,regime);
   return side;
  }

// Passive LIMIT at the last closed M1 close, with frozen bps SL/TP.
// Tick rounding, broker gap and pending-distance cap mirror the shared
// Prepare pattern; the stop is NOT widened to meet a floor — a stop
// that would violate the broker gap fails the order instead, so the
// frozen 12 bps loss is never silently enlarged. anchor is unused
// (kept for dispatch signature parity with PrepareSmcLimit).
bool PrepareScalpLimit(const int side,const MqlTick &tick,const double atr,
                       const double level,const double anchor,
                       double &price,double &stop,double &target)
  {
   if(side==0 || atr<=0.0 || level<=0.0 || tick.ask<=tick.bid || _Point<=0.0)
      return false;
   double step=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(step<=0.0) return false;
   double spread=tick.ask-tick.bid;
   double broker_gap=((double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)+2.0)*_Point;
   double pending_gap=MathMax(broker_gap,2.0*step);
   if(side>0)
     {
      price=NormalizeDouble(MathFloor(level/step)*step,_Digits);
      stop=NormalizeDouble(MathFloor((price* (1.0-SCALP_SL_BPS/10000.0))/step)*step,_Digits);
      target=NormalizeDouble(MathCeil((price*(1.0+SCALP_TP_BPS/10000.0))/step)*step,_Digits);
      if(price<=0.0 || stop<=0.0 || price<=stop ||
         tick.bid-price<pending_gap ||
         tick.ask-price>MaxPendingDistanceAtr*atr ||
         price-stop<broker_gap)
         return false;
      if(target-price<broker_gap) return false;
     }
   else
     {
      price=NormalizeDouble(MathCeil(level/step)*step,_Digits);
      stop=NormalizeDouble(MathCeil((price*(1.0+SCALP_SL_BPS/10000.0))/step)*step,_Digits);
      target=NormalizeDouble(MathFloor((price*(1.0-SCALP_TP_BPS/10000.0))/step)*step,_Digits);
      if(price<=0.0 || stop<=price || price-tick.ask<pending_gap ||
         price-tick.bid>MaxPendingDistanceAtr*atr ||
         stop-price<broker_gap)
         return false;
      if(price-target<broker_gap) return false;
     }
   return true;
  }
