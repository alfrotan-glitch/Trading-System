//+------------------------------------------------------------------+
//| QTS Broker Preflight - readonly XAUUSD@ account/symbol audit      |
//| Intended for WMMarkets MT5 and the QTS Gold Robot research gate. |
//| Reads symbol/account properties, NEVER sends, modifies or closes |
//| an order. A favorable diagnostic is NOT strategy validation.     |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs
#property description "Read-only XAUUSD@ broker, minimum lot, stop-loss and margin audit. NO orders."

input string ExpectedSymbol         = "XAUUSD@";
input double ModelCapitalUsd         = 200.0;
input double ModelRiskPercent        = 0.50;
input double ExampleStopPriceGap     = 4.0;   // Gold price units, e.g. $4/oz; NOT points
input double EstimatedFeePerLotRound = 10.0;  // Account currency/1.0 lot; unverified assumption
input int    MaxTickAgeSeconds       = 15;
input int    MaxSpreadPoints         = 90;

void Record(const int file, const string name, const string value)
  {
   PrintFormat("QTS_PREFLIGHT | %s | %s",name,value);
   if(file!=INVALID_HANDLE)
      FileWrite(file,name,value);
  }

string Money(const double value)
  {
   return DoubleToString(value,2);
  }

void OnStart()
  {
   int report=FileOpen("QTS_Broker_Preflight.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,';');
   if(report==INVALID_HANDLE)
      PrintFormat("QTS PREFLIGHT WARNING: report CSV not writable; error=%d",GetLastError());
   else
      FileWrite(report,"metric","value");

   bool safe=true;
   Record(report,"MODE","READ_ONLY_NO_ORDERS");
   Record(report,"Symbol",_Symbol);
   Record(report,"ExpectedSymbol",ExpectedSymbol);
   Record(report,"BrokerServer",AccountInfoString(ACCOUNT_SERVER));
   Record(report,"AccountCurrency",AccountInfoString(ACCOUNT_CURRENCY));
   Record(report,"AccountType",EnumToString((ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE)));
   Record(report,"ModelCapitalUSD",Money(ModelCapitalUsd));
   Record(report,"ModelRiskPercent",DoubleToString(ModelRiskPercent,2));
   Record(report,"ExampleStopPriceGap",DoubleToString(ExampleStopPriceGap,4));

   if(_Symbol!=ExpectedSymbol || AccountInfoString(ACCOUNT_CURRENCY)!="USD" ||
      ModelCapitalUsd<=0.0 || ModelRiskPercent<=0.0 ||
      ModelRiskPercent>1.0 || ExampleStopPriceGap<=0.0 ||
      EstimatedFeePerLotRound<0.0 || MaxTickAgeSeconds<1)
     {
      safe=false;
      Record(report,"Verdict","BLOCKED_SYMBOL_CURRENCY_OR_INPUTS");
     }
   else
     {
      MqlTick tick={};
      double point=SymbolInfoDouble(_Symbol,SYMBOL_POINT);
      double tick_size=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
      double minimum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
      double maximum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
      double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
      long stops=SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL);
      long freeze=SymbolInfoInteger(_Symbol,SYMBOL_TRADE_FREEZE_LEVEL);
      long trade_mode=SymbolInfoInteger(_Symbol,SYMBOL_TRADE_MODE);
      long order_mode=SymbolInfoInteger(_Symbol,SYMBOL_ORDER_MODE);
      long expiry_mode=SymbolInfoInteger(_Symbol,SYMBOL_EXPIRATION_MODE);
      Record(report,"SymbolTradeMode",IntegerToString(trade_mode));
      Record(report,"SymbolOrderMode",IntegerToString(order_mode));
      Record(report,"SymbolExpirationMode",IntegerToString(expiry_mode));
      Record(report,"MinLot",DoubleToString(minimum,4));
      Record(report,"MaxLot",DoubleToString(maximum,4));
      Record(report,"LotStep",DoubleToString(step,4));
      Record(report,"Point",DoubleToString(point,8));
      Record(report,"TickSize",DoubleToString(tick_size,8));
      Record(report,"StopsLevelPoints",IntegerToString(stops));
      Record(report,"FreezeLevelPoints",IntegerToString(freeze));
      Record(report,"ContractSize",DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE),4));
      Record(report,"ProfitCurrency",SymbolInfoString(_Symbol,SYMBOL_CURRENCY_PROFIT));
      Record(report,"MarginCurrency",SymbolInfoString(_Symbol,SYMBOL_CURRENCY_MARGIN));

      if(point<=0.0 || tick_size<=0.0 || minimum<=0.0 || step<=0.0 ||
         maximum<minimum || stops<0 || freeze<0 ||
         trade_mode!=SYMBOL_TRADE_MODE_FULL ||
         (order_mode & SYMBOL_ORDER_LIMIT)==0 ||
         (order_mode & SYMBOL_ORDER_SL)==0 || (order_mode & SYMBOL_ORDER_TP)==0 ||
         (expiry_mode & SYMBOL_EXPIRATION_SPECIFIED)==0)
        {
         safe=false;
         Record(report,"Verdict","BLOCKED_CONTRACT_OR_TRADE_MODE");
        }
      else if(!SymbolInfoTick(_Symbol,tick) || tick.ask<=tick.bid ||
              tick.bid<=0.0 || tick.time<=0)
        {
         safe=false;
         Record(report,"Verdict","BLOCKED_NO_EXECUTABLE_QUOTE");
        }
      else
        {
         datetime server_now=TimeTradeServer();
         long age=(long)(server_now-tick.time);
         double spread_points=(tick.ask-tick.bid)/point;
         double gap_min=(stops+2)*point;
         double risk_budget=ModelCapitalUsd*ModelRiskPercent/100.0;
         Record(report,"Bid",DoubleToString(tick.bid,_Digits));
         Record(report,"Ask",DoubleToString(tick.ask,_Digits));
         Record(report,"SpreadPoints",DoubleToString(spread_points,1));
         Record(report,"ConfiguredMaxSpreadPoints",IntegerToString(MaxSpreadPoints));
         Record(report,"ServerQuoteAgeSeconds",IntegerToString(age));
         Record(report,"MinStopGapPrice",DoubleToString(gap_min,_Digits));
         Record(report,"ModeledRiskBudgetUSD",Money(risk_budget));
         if(MaxSpreadPoints<=0 || spread_points>MaxSpreadPoints)
           {
            safe=false;
            Record(report,"Verdict","BLOCKED_SPREAD_TOO_WIDE_FOR_EA");
           }
         else if(server_now<=0 || age<0 || age>MaxTickAgeSeconds)
           {
            safe=false;
            Record(report,"Verdict","BLOCKED_STALE_QUOTE_OR_MARKET_CLOSED");
           }
         else if(ExampleStopPriceGap<gap_min || ExampleStopPriceGap<=tick.ask-tick.bid)
           {
            safe=false;
            Record(report,"Verdict","BLOCKED_STOP_GAP_TOO_CLOSE");
           }
         else
           {
            double buy_loss=0.0,sell_loss=0.0;
            double buy_margin=0.0,sell_margin=0.0;
            // Sizing uses broker's trade contract and ACCOUNT currency.
            // It is an estimate; commissions, gaps/slippage can increase losses.
            bool profit_ok=OrderCalcProfit(ORDER_TYPE_BUY,_Symbol,minimum,
                                          tick.ask,tick.ask-ExampleStopPriceGap,buy_loss)
                        && OrderCalcProfit(ORDER_TYPE_SELL,_Symbol,minimum,
                                           tick.bid,tick.bid+ExampleStopPriceGap,sell_loss);
            bool margin_ok=OrderCalcMargin(ORDER_TYPE_BUY,_Symbol,minimum,tick.ask,buy_margin)
                        && OrderCalcMargin(ORDER_TYPE_SELL,_Symbol,minimum,tick.bid,sell_margin);
            if(!profit_ok || !margin_ok ||
               !MathIsValidNumber(buy_loss) || !MathIsValidNumber(sell_loss) ||
               !MathIsValidNumber(buy_margin) || !MathIsValidNumber(sell_margin))
              {
               safe=false;
               Record(report,"Verdict","BLOCKED_BROKER_RISK_OR_MARGIN_CALC_FAILED");
              }
            else
              {
               double fee=minimum*EstimatedFeePerLotRound;
               double worst=MathMax(-buy_loss,-sell_loss)+fee;
               Record(report,"BuyMinLotStopLossUSD",Money(-buy_loss+fee));
               Record(report,"SellMinLotStopLossUSD",Money(-sell_loss+fee));
               Record(report,"ModeledFeeUSD",Money(fee));
               Record(report,"WorstMinLotModeledLossUSD",Money(worst));
               Record(report,"MinLotBuyMarginUSD",Money(buy_margin));
               Record(report,"MinLotSellMarginUSD",Money(sell_margin));
               if(worst>risk_budget || buy_margin>ModelCapitalUsd ||
                  sell_margin>ModelCapitalUsd || worst<=0.0)
                 {
                  safe=false;
                  Record(report,"Verdict","BLOCKED_MIN_LOT_EXCEEDS_MODELED_RISK_OR_MARGIN");
                 }
               else
                  Record(report,"Verdict","ENGINEERING_PRECHECK_OK_NOT_TRADE_PERMISSION");
              }
           }
        }
     }
   Record(report,"OrdersSubmitted","0");
   Record(report,"ActualCommissionVerified","NO");
   Record(report,"StrategyProfitableVerified","NO");
   if(report!=INVALID_HANDLE)
     {
      FileFlush(report);
      FileClose(report);
     }
   if(!safe)
      Alert("QTS BROKER PREFLIGHT: BLOCKED or incomplete. See Experts log and MQL5/Files/QTS_Broker_Preflight.csv");
   else
      Alert("QTS BROKER PREFLIGHT: engineering checks OK (NOT permission to trade). See report CSV.");
  }
