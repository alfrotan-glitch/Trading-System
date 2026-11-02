// QTS native dual opportunity observer. Tester-only, no order operations.
// Records BOTH closed-bar signal families even when an existing position/order
// prevented EvaluateNewEntry from reaching its candidate evaluation.
// The values describe signals, NOT guaranteed executable unfilled trades.
int qts_opportunity_handle=INVALID_HANDLE;
string qts_opportunity_filename="";
long qts_opportunity_bars=0;
long qts_opportunity_rows=0;
bool qts_opportunity_fault=false;

// MQL5 FileWrite(FILE_CSV) inserts semicolon delimiters, but raw status
// strings can ALSO contain semicolons. That creates extra columns and
// invalidates native evidence. Sanitize ONLY text exported to research CSV;
// never mutate status_text, router logic, order requests, or risk checks.
// ASCII bounded text prevents delimiter/newline injection and large records.
string QtsOpportunityCsvSafe(const string raw_text)
  {
   string cleaned=raw_text;
   StringReplace(cleaned,";"," |");
   StringReplace(cleaned,"\r"," ");
   StringReplace(cleaned,"\n"," ");
   StringReplace(cleaned,"\t"," ");
   StringReplace(cleaned,"\"","'");
   if(StringLen(cleaned)>256)
      cleaned=StringSubstr(cleaned,0,256);
   if(StringLen(cleaned)==0)
      cleaned="EMPTY_REASON";
   return cleaned;
  }

bool QtsOpenDualOpportunityLedger()
  {
   if(TesterDualStrategyMode==0)
      return true;
   if(MQLInfoInteger(MQL_TESTER)==0 || EntryStyle!=QTS_ADAPTIVE_ROUTER ||
      SignalTimeframe!=PERIOD_M15)
      return false;
   qts_opportunity_filename=StringFormat("QTS_DUAL_OPPORTUNITY_STYLE_7_%I64u.csv",
                                         GetTickCount64());
   qts_opportunity_handle=FileOpen(qts_opportunity_filename,
                                   FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,';');
   if(qts_opportunity_handle==INVALID_HANDLE)
      return false;
   uint written=FileWrite(qts_opportunity_handle,
       "bar_time_server","observed_time_server","mode","style","side",
       "signal_reason","entry_decision_reason","exposure_blocked",
       "mode_direction_veto","router_eligible_count","router_verdict",
       "atr14_closed","atr_rank_prior_192_pct",
       "adx_closed","h1_close_minus_ema50","bid","ask",
       "spread","candidate_class");
   if(written==0)
     {
      FileClose(qts_opportunity_handle);
      qts_opportunity_handle=INVALID_HANDLE;
      return false;
     }
   FileFlush(qts_opportunity_handle);
   return true;
  }

void QtsObserveDualOpportunities(const datetime bar_time,
                                const string original_entry_reason,
                                const bool exposure_before_decision)
  {
   if(TesterDualStrategyMode==0 || MQLInfoInteger(MQL_TESTER)==0)
      return;
   if(qts_opportunity_handle==INVALID_HANDLE || qts_opportunity_fault ||
      bar_time<=0)
     {
      qts_opportunity_fault=true;
      return;
     }
   int original_style=evaluated_style;
   string original_status=status_text;
   // MQL5 strings passed from a mutable global may alias that global.
   // The signal functions below overwrite status_text on every style.
   // Snapshot the DECISION once, before mutating status_text, and use the
   // independent local string in BOTH rows for the same closed bar.
   string frozen_entry_decision=original_entry_reason;
   MqlTick q={};
   bool quote_ok=SymbolInfoTick(_Symbol,q) && q.ask>q.bid && q.bid>0.0;
   double raw_atr[1],raw_adx[1],raw_h1[1],raw_h1_close[1];
   double atr=-1.0,adx=-1.0,h1_delta=-1.0,rank=-1.0;
   if(CopyBuffer(atr_handle,0,1,1,raw_atr)==1 &&
      MathIsValidNumber(raw_atr[0]) && raw_atr[0]>0.0)
      atr=raw_atr[0];
   if(CopyBuffer(adx_handle,0,1,1,raw_adx)==1 &&
      MathIsValidNumber(raw_adx[0]) && raw_adx[0]>=0.0)
      adx=raw_adx[0];
   // H1 descriptor is NOT an additional strategy veto.
   if(atr>0.0 && h1_handle!=INVALID_HANDLE &&
      CopyBuffer(h1_handle,0,1,1,raw_h1)==1 &&
      CopyClose(_Symbol,PERIOD_H1,1,1,raw_h1_close)==1 &&
      MathIsValidNumber(raw_h1[0]) && raw_h1_close[0]>0.0)
      h1_delta=raw_h1_close[0]-raw_h1[0];
   // Closed-bar ATR rank versus 192 PREVIOUS closed ATR observations.
   // CopyBuffer writes oldest to newest, regardless of as_series setting.
   double previous_atr[];
   if(atr>0.0 && CopyBuffer(atr_handle,0,1,193,previous_atr)==193 &&
      MathIsValidNumber(previous_atr[192]) && previous_atr[192]>0.0)
     {
      bool all_good=true;
      int less_equal=0;
      for(int n=0;n<192;n++)
        {
         if(!MathIsValidNumber(previous_atr[n]) || previous_atr[n]<=0.0)
           {
            all_good=false;
            break;
           }
         if(previous_atr[n]<=previous_atr[192]) less_equal++;
        }
      if(all_good) rank=100.0*(double)less_equal/192.0;
     }
   bool exposure=exposure_before_decision;
   double spread=quote_ok ? q.ask-q.bid : -1.0;
   for(int k=0;k<2;k++)
     {
      int style=k==0 ? QTS_RETEST_LIMIT : QTS_SWEEP_RECLAIM;
      evaluated_style=style;
      double signal_atr=0.0,level=0.0,anchor=0.0;
      int signal=style==QTS_RETEST_LIMIT ?
          CompletedBarSignal(signal_atr) :
          CompletedStructureSignal(signal_atr,level,anchor);
      string signal_reason=status_text;
      // Strictly an observation: no order preparation, lot sizing, trade API,
      // or hypothetical outcome is performed in this loop.
      bool direction_veto=TesterDualStrategyMode==2 && signal!=0 &&
          ((style==QTS_RETEST_LIMIT && signal<0) ||
           (style==QTS_SWEEP_RECLAIM && signal>0));
      string kind=signal==0 ? "NO_SIGNAL" :
          (exposure ? "SIGNAL_WHILE_EXPOSED" :
           (direction_veto ? "MODE_DIRECTION_VETO" : "SIGNAL_NOT_FILL_PROOF"));
      string safe_signal_reason=QtsOpportunityCsvSafe(signal_reason);
      string safe_entry_reason=QtsOpportunityCsvSafe(frozen_entry_decision);
      uint wrote=FileWrite(qts_opportunity_handle,
          TimeToString(bar_time,TIME_DATE|TIME_SECONDS),
          TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),
          TesterDualStrategyMode,style,signal,safe_signal_reason,
          safe_entry_reason,(int)exposure,(int)direction_veto,
          qts_dual_router_eligible,qts_dual_router_verdict,
          DoubleToString(atr,8),DoubleToString(rank,4),
          DoubleToString(adx,6),DoubleToString(h1_delta,6),
          DoubleToString(quote_ok ? q.bid : -1.0,_Digits),
          DoubleToString(quote_ok ? q.ask : -1.0,_Digits),
          DoubleToString(spread,6),kind);
      if(wrote==0) qts_opportunity_fault=true;
      qts_opportunity_rows++;
     }
   qts_opportunity_bars++;
   FileFlush(qts_opportunity_handle);
   evaluated_style=original_style;
   status_text=original_status;
  }

void QtsCloseDualOpportunityLedger()
  {
   if(qts_opportunity_handle!=INVALID_HANDLE)
     {
      FileFlush(qts_opportunity_handle);
      FileClose(qts_opportunity_handle);
      qts_opportunity_handle=INVALID_HANDLE;
     }
  }
