#property strict
// Research-only 2025 H2 fixture; copies cached broker M1 and ticks verbatim.
void OnStart()
{
 string source="XAUUSD@", dest="XAUUSD_QTS_FORWARD";
 datetime begin=D'2025.07.01', end=D'2026.01.01';
 bool custom=false;
 if(!SymbolExist(dest,custom) && !CustomSymbolCreate(dest,"QTS audit",source)) { PrintFormat("FORWARD FIXTURE create failed %d",GetLastError()); return; }
 if(!SymbolSelect(dest,true)) { Print("FORWARD FIXTURE selection failed"); return; }
 MqlRates rates[];
 int n=CopyRates(source,PERIOD_M1,begin,end-1,rates);
 if(n<=0) { PrintFormat("FORWARD FIXTURE no M1 %d",GetLastError()); return; }
 int stored=CustomRatesUpdate(dest,rates);
 if(stored!=n) { PrintFormat("FORWARD FIXTURE M1 mismatch source=%d stored=%d",n,stored); return; }
 long total=0;
 int days=0;
 for(datetime day=begin;day<end;day+=86400)
 {
  MqlTick ticks[];
  int count=CopyTicksRange(source,ticks,COPY_TICKS_ALL,(ulong)day*1000,(ulong)(day+86400)*1000-1);
  if(count<=0) continue;
  int added=CustomTicksReplace(dest,(ulong)day*1000,(ulong)(day+86400)*1000-1,ticks);
  if(added!=count) { PrintFormat("FORWARD FIXTURE ticks mismatch day=%s count=%d stored=%d",TimeToString(day,TIME_DATE),count,added); return; }
  total+=added;
  days++;
  if(days%20==0) PrintFormat("FORWARD FIXTURE days=%d ticks=%I64d",days,total);
 }
 int f=FileOpen("QTS_forward_fixture.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
 if(f!=INVALID_HANDLE) { FileWrite(f,"M1=",stored,"days=",days,"ticks=",total); FileClose(f); }
 PrintFormat("FORWARD FIXTURE complete M1=%d days=%d ticks=%I64d",stored,days,total);
}
