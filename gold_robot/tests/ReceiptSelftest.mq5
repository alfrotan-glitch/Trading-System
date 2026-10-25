#property strict
#include "..\\mt5_robot\\ExecutionPolicy.mqh"
int failures=0;
int cases=0;
void Check(bool sent,uint code,ulong order,ulong deal,QTS_RECEIPT expected)
{
 cases++;
 if(PendingReceipt(sent,code,order,deal)!=expected) { failures++; PrintFormat("FAIL receipt case %d",cases); }
}
void OnStart()
{
 Check(true,10009,2,0,QTS_ACCEPTED);
 Check(true,10008,2,0,QTS_ACCEPTED);
 Check(true,10010,2,3,QTS_ACCEPTED);
 Check(true,10009,0,0,QTS_AMBIGUOUS);
 Check(false,10009,2,0,QTS_AMBIGUOUS);
 Check(false,10012,0,0,QTS_AMBIGUOUS);
 Check(false,10031,0,0,QTS_AMBIGUOUS);
 Check(false,10016,0,0,QTS_REJECTED);
 Check(true,10016,2,0,QTS_AMBIGUOUS);
 Check(false,10018,0,0,QTS_REJECTED);
 Check(true,10009,0,3,QTS_AMBIGUOUS);
 Check(false,99999,0,0,QTS_AMBIGUOUS);
 int f=FileOpen("QTS_receipt_test.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
 if(f!=INVALID_HANDLE) { FileWrite(f,"cases",cases,"failures",failures); FileClose(f); }
 PrintFormat("QTS RECEIPT TEST: %d cases, %d failures",cases,failures);
}
