// QTS Gold closed-bar multi-timeframe contextual veto, V3 hypothesis.
// Strategy Tester ONLY; opt-in OFF by default, LIVE/DEMO unchanged.
// This is a FILTER on the existing adaptive LIMIT order, not an edge claim.
// No current (shift=0) candle is read; no future data, no news assumptions.
// Native MT5 broker time is not automatically London/New York local time.
#define QTS_V3_M15_HISTORY 18

// Native tester-only source-of-truth counts for every V3 rejection reason.
// Historic logs are not sufficient: export this even if no order ever existed.
#define QTS_V3_REJECTION_REASONS 25
int g_v3_rejection_counts[QTS_V3_REJECTION_REASONS];
int g_v3_accepted_count=0;
string V3ReasonText(const int idx)
  {
   string reasons[]={
      "not an authorized M15 adaptive tester",
      "M15/M5/H1 closed bars unavailable",
      "M15 signal bar not closed at evaluation",
      "M15 history gap; do not infer structure",
      "M5 confirmation not aligned with M15 decision",
      "H1 candle not causally available",
      "higher-timeframe indicators unavailable",
      "missing supported trade direction",
      "invalid volatility, tick or planned prices",
      "invalid previous M15 price structure",
      "last closed candle data invalid",
      "SL/entry/TP direction invalid",
      "weak SL room or gross reward/risk",
      "spread dominates ATR or structural stop",
      "unsupported router family",
      "H1 directional trend or M15 EMA rejected",
      "M5 closed candle did not confirm direction",
      "range BUY lacks support reclaim",
      "BUY sweep did not pierce prior support",
      "range SELL lacks resistance rejection",
      "SELL sweep did not pierce prior resistance",
      "minimum broker lot is unknown",
      "broker did not quote planned profit",
      "after-cost and slipped-stop reward/risk below 1.25",
      "UNKNOWN_V3_VETO"
   };
   if(idx<0 || idx>=ArraySize(reasons)) return "UNKNOWN_V3_VETO";
   return reasons[idx];
  }
string V3ReasonCode(const int idx)
  {
   string codes[]={
      "UNAUTHORIZED_M15",
      "M15_M5_H1_BARS_MISSING",
      "M15_BAR_NOT_CLOSED",
      "M15_HISTORY_GAP",
      "M5_M15_MISALIGNED",
      "H1_BAR_NOT_CAUSAL",
      "EMA_INDICATORS_MISSING",
      "INVALID_TRADE_SIDE",
      "INVALID_ATR_QUOTE_PRICE",
      "INVALID_M15_PRIOR_STRUCTURE",
      "INVALID_CLOSED_CANDLE",
      "INVALID_SL_ENTRY_TP_DIRECTION",
      "WEAK_STOP_ROOM_OR_GROSS_RR",
      "SPREAD_OR_STOP_ROOM",
      "UNSUPPORTED_STRATEGY_FAMILY",
      "H1_TREND_OR_M15_EMA",
      "M5_DIRECTION_NOT_CONFIRMED",
      "RANGE_BUY_NO_SUPPORT_RECLAIM",
      "BUY_SWEEP_NO_SUPPORT_PIERCE",
      "RANGE_SELL_NO_RESISTANCE_REJECT",
      "SELL_SWEEP_NO_RESISTANCE_PIERCE",
      "BROKER_MINIMUM_LOT_UNKNOWN",
      "BROKER_PROFIT_QUOTE_UNAVAILABLE",
      "NET_RR_BELOW_1_25",
      "UNKNOWN_V3_VETO"
   };
   if(idx<0 || idx>=ArraySize(codes)) return "UNKNOWN_V3_VETO";
   return codes[idx];
  }
void V3CountRejection(const string why)
  {
   if(MQLInfoInteger(MQL_TESTER)==0 || !TesterUseMarketContextV3) return;
   int idx=QTS_V3_REJECTION_REASONS-1;
   for(int i=0;i<QTS_V3_REJECTION_REASONS-1;i++)
      if(why==V3ReasonText(i))
        {
         idx=i;
         break;
        }
   g_v3_rejection_counts[idx]++;
  }

bool MarketContextV3Reject(const string why)
  {
   V3CountRejection(why);
   status_text="V3 MARKET CONTEXT: "+why;
   if(EnableEntryDiagnostics)
      Print("QTS V3 veto closed-bar market context: ",why);
   return false;
  }

// Evaluate only after the adaptive router selected a real completed-bar
// candidate and PRE-ORDER, before risk sizing / OrderCheck / OrderSend.
bool TesterMarketContextV3(const int side,const int style,
                           const MqlTick &quote,const double atr,
                           const double entry,const double stop,
                           const double target)
  {
   if(!TesterUseMarketContextV3)
      return true;
   if(MQLInfoInteger(MQL_TESTER)==0 || EntryStyle!=QTS_ADAPTIVE_ROUTER ||
      SignalTimeframe!=PERIOD_M15 || h1_handle==INVALID_HANDLE)
      return MarketContextV3Reject("not an authorized M15 adaptive tester");

   MqlRates m15[QTS_V3_M15_HISTORY],m5[2],h1[1];
   // start_pos=1 excludes the still-forming bar in every timeframe.
   // CopyRates physical arrays are oldest-to-newest, so m15[17],
   // m5[1] and h1[0] refer to the last completed candles.
   if(CopyRates(_Symbol,PERIOD_M15,1,QTS_V3_M15_HISTORY,m15)!=QTS_V3_M15_HISTORY ||
      CopyRates(_Symbol,PERIOD_M5,1,2,m5)!=2 ||
      CopyRates(_Symbol,PERIOD_H1,1,1,h1)!=1)
      return MarketContextV3Reject("M15/M5/H1 closed bars unavailable");
   datetime asof=iTime(_Symbol,PERIOD_M15,0);
   if(asof<=0 || m15[QTS_V3_M15_HISTORY-1].time+900!=asof)
      return MarketContextV3Reject("M15 signal bar not closed at evaluation");
   for(int k=1;k<QTS_V3_M15_HISTORY;k++)
      if(m15[k].time-m15[k-1].time!=900)
         return MarketContextV3Reject("M15 history gap; do not infer structure");
   if(m5[1].time-m5[0].time!=300 ||
      m5[1].time+300>asof ||
      asof-(m5[1].time+300)>300)
      return MarketContextV3Reject("M5 confirmation not aligned with M15 decision");
   if(h1[0].time+3600>asof ||
      asof-(h1[0].time+3600)>3600)
      return MarketContextV3Reject("H1 candle not causally available");
   double h1_ema[1],m15_ema[1];
   if(CopyBuffer(h1_handle,0,1,1,h1_ema)!=1 ||
      CopyBuffer(fast_handle,0,1,1,m15_ema)!=1 ||
      !MathIsValidNumber(h1_ema[0]) || !MathIsValidNumber(m15_ema[0]) ||
      h1_ema[0]<=0.0 || m15_ema[0]<=0.0)
      return MarketContextV3Reject("higher-timeframe indicators unavailable");
   if(side!=1 && side!=-1)
      return MarketContextV3Reject("missing supported trade direction");
   if(atr<=0.0 || !MathIsValidNumber(atr) || quote.ask<=quote.bid ||
      entry<=0.0 || stop<=0.0 || target<=0.0 ||
      !MathIsValidNumber(entry) || !MathIsValidNumber(stop) ||
      !MathIsValidNumber(target))
      return MarketContextV3Reject("invalid volatility, tick or planned prices");

   const int last=QTS_V3_M15_HISTORY-1;
   double support=DBL_MAX,resistance=0.0;
   for(int i=0;i<last;i++)
     {
      if(m15[i].low<=0.0 || m15[i].high<m15[i].low ||
         !MathIsValidNumber(m15[i].close))
         return MarketContextV3Reject("invalid previous M15 price structure");
      support=MathMin(support,m15[i].low);
      resistance=MathMax(resistance,m15[i].high);
     }
   if(m15[last].high<m15[last].low ||
      m15[last].close<=0.0 || m5[1].close<=0.0)
      return MarketContextV3Reject("last closed candle data invalid");
   double gap=MathAbs(entry-stop),gross=MathAbs(target-entry);
   if((side>0 && !(stop<entry && entry<target)) ||
      (side<0 && !(target<entry && entry<stop)))
      return MarketContextV3Reject("SL/entry/TP direction invalid");
   if(gap<0.35*atr || gross<gap*1.25)
      return MarketContextV3Reject("weak SL room or gross reward/risk");
   double spread=quote.ask-quote.bid;
   if(spread>0.15*atr || gap<3.0*spread)
      return MarketContextV3Reject("spread dominates ATR or structural stop");

   bool trend_style=(style==QTS_RETEST_LIMIT ||
                     style==QTS_BREAK_ACCEPT_RETEST ||
                     style==QTS_TREND_IMPULSE ||
                     style==QTS_INSIDE_BREAKOUT ||
                     style==QTS_SMC_FVG_OB);
   bool range_style=(style==QTS_FORMER_STOP_LIMIT ||
                     style==QTS_SWEEP_RECLAIM ||
                     style==QTS_RANGE_REJECTION);
   if(!trend_style && !range_style)
      return MarketContextV3Reject("unsupported router family");

   if(trend_style)
     {
      if((side>0 && (h1[0].close<=h1_ema[0] ||
                    m15[last].close<m15_ema[0]-0.35*atr)) ||
         (side<0 && (h1[0].close>=h1_ema[0] ||
                    m15[last].close>m15_ema[0]+0.35*atr)))
         return MarketContextV3Reject("H1 directional trend or M15 EMA rejected");
      if((side>0 && (m5[1].close<=m5[1].open ||
                     m5[1].close<m5[0].close)) ||
         (side<0 && (m5[1].close>=m5[1].open ||
                     m5[1].close>m5[0].close)))
         return MarketContextV3Reject("M5 closed candle did not confirm direction");
     }
   else
     {
      // A range candidate must originate near an OBSERVED past boundary.
      // For sweep style require closed bar to reclaim that prior boundary.
      if(side>0)
        {
         if(m15[last].low>support+0.50*atr ||
            m15[last].close<=support)
            return MarketContextV3Reject("range BUY lacks support reclaim");
         if(style==QTS_SWEEP_RECLAIM && m15[last].low>=support)
            return MarketContextV3Reject("BUY sweep did not pierce prior support");
        }
      else
        {
         if(m15[last].high<resistance-0.50*atr ||
            m15[last].close>=resistance)
            return MarketContextV3Reject("range SELL lacks resistance rejection");
         if(style==QTS_SWEEP_RECLAIM && m15[last].high<=resistance)
            return MarketContextV3Reject("SELL sweep did not pierce prior resistance");
        }
     }
   double min_lot=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   if(min_lot<=0.0)
      return MarketContextV3Reject("minimum broker lot is unknown");
   double gross_tp=0.0;
   ENUM_ORDER_TYPE direction=side>0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(!OrderCalcProfit(direction,_Symbol,min_lot,entry,target,gross_tp))
      return MarketContextV3Reject("broker did not quote planned profit");
   double risk=EstimatedMonetaryLoss(side,min_lot,entry,stop);
   double net_tp=gross_tp-AssumedRoundTurnFeePerLot*min_lot;
   if(risk<=0.0 || net_tp<=0.0 || net_tp/risk<1.25)
      return MarketContextV3Reject("after-cost and slipped-stop reward/risk below 1.25");
   if(MQLInfoInteger(MQL_TESTER)!=0) g_v3_accepted_count++;
   if(EnableEntryDiagnostics)
      PrintFormat("QTS V3 ACCEPT research-only style=%d side=%d H1=%.5f H1_EMA=%.5f M15=%.5f M5=%.5f support=%.5f resistance=%.5f netRR=%.3f",
                  style,side,h1[0].close,h1_ema[0],m15[last].close,
                  m5[1].close,support,resistance,net_tp/risk);
   return true;
  }
