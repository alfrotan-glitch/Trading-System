#property strict
#property script_show_inputs
// QTS: read-only, bounded native WMMarkets quote export for recorded SLs.
// Install in the SAME terminal as the EA. NEVER places an order.
input string InpSymbol="XAUUSD@";

void OnStart()
{
   if(!SymbolSelect(InpSymbol,true))
   {
      PrintFormat("QTS STOP TICKS: symbol unavailable %s error=%d",InpSymbol,GetLastError());
      return;
   }
   int source=FileOpen("QTS_STOP_WINDOWS.csv",FILE_READ|FILE_CSV|FILE_ANSI,';');
   if(source==INVALID_HANDLE)
   {
      PrintFormat("QTS STOP TICKS: missing QTS_STOP_WINDOWS.csv error=%d",GetLastError());
      return;
   }
   int index=0,failures=0;
   long written=0;
   string export_folder="";
   string expected_tag="";
   while(!FileIsEnding(source) && index<5000)
   {
      string start_text=FileReadString(source);
      if(FileIsEnding(source) && start_text=="") break;
      string end_text=FileReadString(source);
      string tag=FileReadString(source);
      long from_ms=StringToInteger(start_text);
      long until_ms=StringToInteger(end_text);
      if(from_ms<1577836800000 || until_ms<=from_ms ||
         until_ms>4102444800000 || StringLen(tag)!=15)
      {
         PrintFormat("QTS STOP TICKS: invalid bounded window %d",index);
         failures++;
         break;
      }
      if(index==0)
      {
         expected_tag=tag;
         export_folder="QTS_STOP_TICKS_"+tag;
      }
      if(tag!=expected_tag)
      {
         Print("QTS STOP TICKS: mismatched run tag");
         failures++;
         break;
      }
      index++;
      string tick_file=export_folder+"\\"+StringFormat("ticks_%05d.csv",index);
      int handle=FileOpen(tick_file,FILE_WRITE|FILE_CSV|FILE_ANSI,',');
      if(handle==INVALID_HANDLE)
      {
         PrintFormat("QTS STOP TICKS: cannot write %s error=%d",tick_file,GetLastError());
         failures++;
         break;
      }
      FileWrite(handle,"time_msc","bid","ask");
      long interval_count=0;
      ulong cursor=(ulong)from_ms;
      ulong ceiling=(ulong)until_ms;
      while(cursor<=ceiling)
      {
         ulong end_chunk=cursor+899999; // at most 15 min per tick-history call
         if(end_chunk>ceiling) end_chunk=ceiling;
         MqlTick rows[];
         ResetLastError();
         int count=CopyTicksRange(InpSymbol,rows,COPY_TICKS_ALL,cursor,end_chunk);
         if(count<0)
         {
            PrintFormat("QTS STOP TICKS: missing broker ticks window=%d code=%d",index,GetLastError());
            failures++;
            break;
         }
         for(int i=0;i<count;i++)
         {
            if(rows[i].bid<=0.0 || rows[i].ask<rows[i].bid) continue;
            FileWrite(handle,rows[i].time_msc,
                      DoubleToString(rows[i].bid,8),DoubleToString(rows[i].ask,8));
            interval_count++;
            written++;
         }
         cursor=end_chunk+1;
      }
      FileClose(handle);
      if(interval_count==0)
      {
         PrintFormat("QTS STOP TICKS: no executable quotes window=%d",index);
         failures++;
      }
      PrintFormat("QTS STOP TICKS: window=%d ticks=%I64d",index,interval_count);
   }
   if(index>=5000 && !FileIsEnding(source)) failures++;
   FileClose(source);
   if(index==0)
   {
      Print("QTS STOP TICKS: no bounded windows; no quotes exported");
      return;
   }
   string status_file=export_folder+"\\export_status.csv";
   int status=FileOpen(status_file,FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   if(status==INVALID_HANDLE)
   {
      PrintFormat("QTS STOP TICKS: cannot save status error=%d",GetLastError());
      return;
   }
   FileWrite(status,"state","windows","failures","quotes");
   FileWrite(status,failures==0?"COMPLETE":"INCOMPLETE",index,failures,written);
   FileClose(status);
   PrintFormat("QTS STOP TICKS: export=%s windows=%d failures=%d quotes=%I64d. REAL MONEY LOCKED.",
               export_folder,index,failures,written);
}
