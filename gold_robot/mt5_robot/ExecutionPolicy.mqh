// Pure receipt policy. A submission receipt is NEVER proof of a fill.
enum QTS_RECEIPT { QTS_AMBIGUOUS=0, QTS_ACCEPTED=1, QTS_REJECTED=2 };
QTS_RECEIPT PendingReceipt(const bool sent,const uint code,
                           const ulong order,const ulong deal)
  {
   if(sent && order>0 && (code==TRADE_RETCODE_PLACED ||
                         code==TRADE_RETCODE_DONE ||
                         code==TRADE_RETCODE_DONE_PARTIAL))
      return QTS_ACCEPTED;
   // A ticket with a negative/contradictory receipt needs reconciliation.
   if(order>0 || deal>0) return QTS_AMBIGUOUS;
   switch(code)
     {
      case TRADE_RETCODE_REQUOTE:
      case TRADE_RETCODE_REJECT:
      case TRADE_RETCODE_INVALID:
      case TRADE_RETCODE_INVALID_VOLUME:
      case TRADE_RETCODE_INVALID_PRICE:
      case TRADE_RETCODE_INVALID_STOPS:
      case TRADE_RETCODE_TRADE_DISABLED:
      case TRADE_RETCODE_MARKET_CLOSED:
      case TRADE_RETCODE_NO_MONEY:
      case TRADE_RETCODE_PRICE_CHANGED:
      case TRADE_RETCODE_PRICE_OFF:
      case TRADE_RETCODE_INVALID_EXPIRATION:
      case TRADE_RETCODE_TOO_MANY_REQUESTS:
      case TRADE_RETCODE_SERVER_DISABLES_AT:
      case TRADE_RETCODE_CLIENT_DISABLES_AT:
      case TRADE_RETCODE_INVALID_FILL:
      case TRADE_RETCODE_LIMIT_ORDERS:
      case TRADE_RETCODE_LIMIT_VOLUME:
      case TRADE_RETCODE_INVALID_ORDER:
         return QTS_REJECTED;
     }
   return QTS_AMBIGUOUS; // Timeout, connection loss, unknown codes, no ticket.
  }

bool QtsFillStopsConsistent(const int direction,const double fill_price,
                            const double initial_sl,const double initial_tp)
  {
   if(direction!=1 && direction!=-1) return false;
   if(fill_price<=0 || initial_sl<=0 || initial_tp<=0)
      return false;
   if(!MathIsValidNumber(fill_price) || !MathIsValidNumber(initial_sl) ||
      !MathIsValidNumber(initial_tp)) return false;
   if(direction==1) return initial_sl<fill_price && fill_price<initial_tp;
   return initial_tp<fill_price && fill_price<initial_sl;
  }
