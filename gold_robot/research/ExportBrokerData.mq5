#property strict
// Read-only research export; never submits orders.
void OnStart()
{
 string s="XAUUSD@";
 datetime begin=D'2024.09.01', end=D'2026.10.24';
 if(!SymbolSelect(s,true)) return;
 FolderCreate("QTS_research");
 int f=FileOpen("QTS_research\\spec.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
 if(f==INVALID_HANDLE) return;
 FileWrite(f,"symbol","server","point","tick_size","contract_size","volume_min","volume_max","volume_step","stops_level","expiration_mode");
 FileWrite(f,s,AccountInfoString(ACCOUNT_SERVER),SymbolInfoDouble(s,SYMBOL_POINT),SymbolInfoDouble(s,SYMBOL_TRADE_TICK_SIZE),SymbolInfoDouble(s,SYMBOL_TRADE_CONTRACT_SIZE),SymbolInfoDouble(s,SYMBOL_VOLUME_MIN),SymbolInfoDouble(s,SYMBOL_VOLUME_MAX),SymbolInfoDouble(s,SYMBOL_VOLUME_STEP),SymbolInfoInteger(s,SYMBOL_TRADE_STOPS_LEVEL),SymbolInfoInteger(s,SYMBOL_EXPIRATION_MODE));
 FileClose(f);
 MqlRates bars[];
 int n=CopyRates(s,PERIOD_M15,begin,end-1,bars);
 if(n<=0) { PrintFormat("QTS EXPORT: no bars error=%d",GetLastError()); return; }
 f=FileOpen("QTS_research\\bars.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
 if(f==INVALID_HANDLE) return;
 FileWrite(f,"time","open","high","low","close","tick_volume","spread");
 for(int i=0;i<n;i++) FileWrite(f,(long)bars[i].time,DoubleToString(bars[i].open,8),DoubleToString(bars[i].high,8),DoubleToString(bars[i].low,8),DoubleToString(bars[i].close,8),bars[i].tick_volume,bars[i].spread);
 FileClose(f);
 PrintFormat("QTS EXPORT: %d M15 bars",n);
 for(datetime day=begin;day<end;day+=86400)
 {
  MqlTick ticks[];
  datetime until=(day+86400<end ? day+86400 : end);
  int count=CopyTicksRange(s,ticks,COPY_TICKS_ALL,(ulong)day*1000,(ulong)until*1000-1);
  if(count<=0) { PrintFormat("QTS EXPORT: no ticks %s error=%d",TimeToString(day,TIME_DATE),GetLastError()); continue; }
  string name=StringFormat("QTS_research\\ticks_%I64d.csv",(long)day);
  f=FileOpen(name,FILE_WRITE|FILE_CSV|FILE_ANSI,',');
  if(f==INVALID_HANDLE) return;
  FileWrite(f,"time_msc","bid","ask");
  for(int i=0;i<count;i++) FileWrite(f,ticks[i].time_msc,DoubleToString(ticks[i].bid,8),DoubleToString(ticks[i].ask,8));
  FileClose(f);
  PrintFormat("QTS EXPORT: %s ticks=%d",name,count);
 }
 Print("QTS EXPORT finished; missing days require audit.");
}
