#property strict
// Offline tester fixture: broker cache copied verbatim into a custom symbol.
// This is not another EA and cannot place trades.
void OnStart()
{
 string source="XAUUSD@", dest="XAUUSD_QTS_AUDIT";
 datetime begin=D'2025.01.01', end=D'2025.07.01';
 bool custom=false;
 if(!SymbolExist(dest,custom) && !CustomSymbolCreate(dest,"QTS audit",source)) { PrintFormat("FIXTURE create failed %d",GetLastError()); return; }
 if(!SymbolSelect(dest,true)) return;
 MqlRates rates[];
 int n=CopyRates(source,PERIOD_M1,begin,end-1,rates);
 if(n<=0) { PrintFormat("FIXTURE no M1 %d",GetLastError()); return; }
 int stored=CustomRatesUpdate(dest,rates);
 PrintFormat("FIXTURE M1 copied=%d stored=%d",n,stored);
 long total=0;
 for(datetime day=begin;day<end;day+=86400)
 {
  MqlTick ticks[];
  int count=CopyTicksRange(source,ticks,COPY_TICKS_ALL,(ulong)day*1000,(ulong)(day+86400)*1000-1);
  if(count<=0) continue;
  int added=CustomTicksReplace(dest,(ulong)day*1000,(ulong)(day+86400)*1000-1,ticks);
  if(added!=count) { PrintFormat("FIXTURE ticks mismatch day=%s count=%d stored=%d",TimeToString(day,TIME_DATE),count,added); return; }
  total+=added;
 }
 int f=FileOpen("QTS_fixture.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
 if(f!=INVALID_HANDLE) { FileWrite(f,"M1=",stored,"ticks=",total); FileClose(f); }
 PrintFormat("FIXTURE complete M1=%d ticks=%I64d",stored,total);
}
