//+------------------------------------------------------------------+
//|                                                     CoreDefs.mqh |
//|            Shared types, enums and helpers for the XAUUSD FTMO EA |
//+------------------------------------------------------------------+
#property copyright "XAUUSD FTMO Confluence EA"
#property link      ""
#ifndef __XAUUSD_FTMO_COREDEFS_MQH__
#define __XAUUSD_FTMO_COREDEFS_MQH__

//--- news impact levels (mapped from both ForexFactory and the MT5 calendar)
#define NEWS_IMPACT_NONE     0
#define NEWS_IMPACT_LOW      1
#define NEWS_IMPACT_MEDIUM   2
#define NEWS_IMPACT_HIGH     3

//--- trade direction
enum ENUM_SIGNAL_DIR
  {
   SIGNAL_NONE = 0,
   SIGNAL_BUY  = 1,
   SIGNAL_SELL = -1
  };

//--- which calendar feed the news filter should consult
enum ENUM_NEWS_SOURCE
  {
   NEWS_SRC_OFF        = 0,  // Off - no news filtering (not FTMO compliant)
   NEWS_SRC_MT5        = 1,  // MT5 built-in economic calendar only
   NEWS_SRC_FOREXFACTORY = 2,  // ForexFactory weekly feed only (needs WebRequest)
   NEWS_SRC_BOTH       = 3   // ForexFactory + MT5 calendar (recommended)
  };

//--- how the EA sizes each trade
enum ENUM_RISK_MODE
  {
   RISK_PERCENT_BALANCE = 0, // % of account balance
   RISK_PERCENT_EQUITY  = 1, // % of account equity
   RISK_PERCENT_INITIAL = 2, // % of the initial (challenge) capital  <- FTMO safe
   RISK_FIXED_LOT       = 3  // fixed lot size
  };

//--- what the EA does when a compliance guard trips
enum ENUM_GUARD_ACTION
  {
   GUARD_NONE        = 0,  // nothing tripped, trading allowed
   GUARD_SOFT_HALT   = 1,  // no NEW trades, existing positions managed
   GUARD_HARD_FLAT   = 2   // close everything and stop for the day/phase
  };

//--- a single high impact calendar entry, already normalised to server time
struct NewsEvent
  {
   datetime          time;      // event time in BROKER SERVER time
   int               impact;    // NEWS_IMPACT_*
   string            currency;  // USD, EUR, XAU, ALL ...
   string            title;     // human readable event name
  };

//--- one scored confluence component, kept for the dashboard / journal
struct ConfluenceItem
  {
   string            name;
   double            weight;    // maximum points this component can award
   double            bull;      // points awarded to the bullish case
   double            bear;      // points awarded to the bearish case
  };

//--- the fully evaluated signal for the current bar
struct SignalSnapshot
  {
   ENUM_SIGNAL_DIR   dir;
   double            bullScore;
   double            bearScore;
   double            atr;
   double            entry;
   double            stop;
   double            tp1;
   double            tp2;
   double            riskDistance;   // |entry - stop| in price terms
   string            reason;         // why the signal was rejected, if it was
  };

//+------------------------------------------------------------------+
//| Rounds a price to the symbol's tick size.                        |
//+------------------------------------------------------------------+
double NormalizePriceToTick(const string symbol, const double price)
  {
   double tick = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick <= 0.0)
      return NormalizeDouble(price, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS));
   double rounded = MathRound(price / tick) * tick;
   return NormalizeDouble(rounded, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS));
  }

//+------------------------------------------------------------------+
//| Clamps a volume to the symbol's min / max / step constraints.    |
//+------------------------------------------------------------------+
double NormalizeVolume(const string symbol, double volume)
  {
   double minLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);

   if(lotStep <= 0.0)
      lotStep = 0.01;

   volume = MathFloor(volume / lotStep) * lotStep;

   if(volume < minLot)
      volume = 0.0;              // caller decides whether to skip or floor
   if(maxLot > 0.0 && volume > maxLot)
      volume = maxLot;

   int stepDigits = 2;
   if(lotStep >= 1.0)
      stepDigits = 0;
   else
      if(lotStep >= 0.1)
         stepDigits = 1;
      else
         if(lotStep >= 0.01)
            stepDigits = 2;
         else
            stepDigits = 3;

   return NormalizeDouble(volume, stepDigits);
  }

//+------------------------------------------------------------------+
//| Money value of one point for one lot of the given symbol.        |
//| Falls back to a contract-size derivation when the broker does    |
//| not expose a usable tick value (happens on some XAUUSD feeds).   |
//+------------------------------------------------------------------+
double PointValuePerLot(const string symbol)
  {
   double tickValue = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double point     = SymbolInfoDouble(symbol, SYMBOL_POINT);

   if(tickValue > 0.0 && tickSize > 0.0 && point > 0.0)
      return tickValue * (point / tickSize);

   // fallback: assume a USD quoted metal, 1 lot = contract size ounces
   double contract = SymbolInfoDouble(symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   if(contract > 0.0 && point > 0.0)
      return contract * point;

   return 0.0;
  }

//+------------------------------------------------------------------+
//| Converts a price distance into money for a given lot size.       |
//+------------------------------------------------------------------+
double MoneyForDistance(const string symbol, const double priceDistance, const double lots)
  {
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   if(point <= 0.0)
      return 0.0;
   double points = priceDistance / point;
   return points * PointValuePerLot(symbol) * lots;
  }

//+------------------------------------------------------------------+
//| Broker server time offset from GMT, in seconds.                  |
//| Auto-detected when possible, otherwise the manual override wins. |
//+------------------------------------------------------------------+
int ServerGmtOffsetSeconds(const int manualOverrideHours, const bool useManual)
  {
   if(useManual)
      return manualOverrideHours * 3600;

   datetime srv = TimeTradeServer();
   datetime gmt = TimeGMT();
   if(srv <= 0 || gmt <= 0)
      return manualOverrideHours * 3600;

   // round to the nearest half hour to absorb clock jitter
   double diff = (double)(srv - gmt);
   double halfHours = MathRound(diff / 1800.0);
   return (int)(halfHours * 1800.0);
  }

//+------------------------------------------------------------------+
//| Start of the calendar day (00:00) that contains 't'.             |
//+------------------------------------------------------------------+
datetime DayStart(const datetime t)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   s.hour = 0;
   s.min  = 0;
   s.sec  = 0;
   return StructToTime(s);
  }

//+------------------------------------------------------------------+
//| Minutes elapsed since midnight for the supplied timestamp.       |
//+------------------------------------------------------------------+
int MinutesOfDay(const datetime t)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   return s.hour * 60 + s.min;
  }

//+------------------------------------------------------------------+
//| True when 'minute' falls inside [fromMin, toMin], wrap aware.    |
//+------------------------------------------------------------------+
bool InMinuteWindow(const int minute, const int fromMin, const int toMin)
  {
   if(fromMin == toMin)
      return false;
   if(fromMin < toMin)
      return (minute >= fromMin && minute < toMin);
   return (minute >= fromMin || minute < toMin);   // window crosses midnight
  }

//+------------------------------------------------------------------+
//| Parses "HH:MM" into minutes since midnight. -1 when malformed.   |
//+------------------------------------------------------------------+
int ParseHHMM(const string hhmm)
  {
   string parts[];
   int n = StringSplit(hhmm, ':', parts);
   if(n != 2)
      return -1;
   int h = (int)StringToInteger(parts[0]);
   int m = (int)StringToInteger(parts[1]);
   if(h < 0 || h > 23 || m < 0 || m > 59)
      return -1;
   return h * 60 + m;
  }

#endif // __XAUUSD_FTMO_COREDEFS_MQH__
//+------------------------------------------------------------------+
