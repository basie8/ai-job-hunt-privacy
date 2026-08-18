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

//--- what the EA is doing right now, as shown on the console banner
enum ENUM_EA_STATUS
  {
   EA_STATUS_ACTIVE          = 0,  // in session, guards clear, hunting for a setup
   EA_STATUS_IN_TRADE        = 1,  // position open and being managed
   EA_STATUS_PAUSED_NEWS     = 2,  // high-impact news blackout
   EA_STATUS_PAUSED_SESSION  = 3,  // outside the trading sessions
   EA_STATUS_PAUSED_RISK     = 4,  // a soft drawdown guard is holding trading
   EA_STATUS_PAUSED_LIMIT    = 5,  // trade cap, entry spacing, spread or streak
   EA_STATUS_CLOSED_WEEKEND  = 6,  // weekend / Friday cutoff
   EA_STATUS_TARGET_REACHED  = 7,  // phase target hit, standing down
   EA_STATUS_HALTED          = 8   // hard guard tripped - flat and stopped
  };

//+------------------------------------------------------------------+
string StatusLabel(const ENUM_EA_STATUS s)
  {
   switch(s)
     {
      case EA_STATUS_ACTIVE:         return "ACTIVE";
      case EA_STATUS_IN_TRADE:       return "IN TRADE";
      case EA_STATUS_PAUSED_NEWS:    return "PAUSED - NEWS";
      case EA_STATUS_PAUSED_SESSION: return "CLOSED - SESSION";
      case EA_STATUS_PAUSED_RISK:    return "PAUSED - RISK GUARD";
      case EA_STATUS_PAUSED_LIMIT:   return "PAUSED - LIMIT";
      case EA_STATUS_CLOSED_WEEKEND: return "CLOSED - WEEKEND";
      case EA_STATUS_TARGET_REACHED: return "TARGET REACHED";
      case EA_STATUS_HALTED:         return "HALTED";
     }
   return "UNKNOWN";
  }

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
//| Number of decimals implied by the broker's lot step.             |
//+------------------------------------------------------------------+
int LotStepDigits(const double lotStep)
  {
   if(lotStep >= 1.0)   return 0;
   if(lotStep >= 0.1)   return 1;
   if(lotStep >= 0.01)  return 2;
   return 3;
  }

//+------------------------------------------------------------------+
//| Clamps a volume to the symbol's min / max / step constraints.    |
//|                                                                  |
//| The epsilon matters. volume/lotStep is a binary float, so 0.29   |
//| over a 0.01 step evaluates to 28.999999999999996 and a bare      |
//| MathFloor silently drops a whole lot step. Three of six ordinary |
//| gold volumes are affected. Nudging by a fraction of a step       |
//| before flooring removes the error without ever rounding up past  |
//| a real step boundary.                                            |
//|                                                                  |
//| Returns 0.0 when the result is below the broker minimum; the     |
//| caller must treat that as "cannot trade", never as "trade min".  |
//+------------------------------------------------------------------+
double NormalizeVolume(const string symbol, double volume)
  {
   double minLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double volLimit = SymbolInfoDouble(symbol, SYMBOL_VOLUME_LIMIT);

   if(lotStep <= 0.0)
      lotStep = 0.01;

   if(volume <= 0.0)
      return 0.0;

   volume = MathFloor(volume / lotStep + 1e-8) * lotStep;

   // SYMBOL_VOLUME_LIMIT caps the total volume allowed on the symbol and is
   // stricter than VOLUME_MAX on some brokers. Zero means "no limit".
   if(volLimit > 0.0 && volume > volLimit)
      volume = MathFloor(volLimit / lotStep + 1e-8) * lotStep;

   if(maxLot > 0.0 && volume > maxLot)
      volume = MathFloor(maxLot / lotStep + 1e-8) * lotStep;

   if(minLot > 0.0 && volume < minLot - 1e-8)
      return 0.0;                // caller decides whether to skip

   return NormalizeDouble(volume, LotStepDigits(lotStep));
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
//| Broker contract pre-flight.                                      |
//|                                                                  |
//| Prints every symbol constraint the EA depends on and fails when  |
//| one of them makes trading impossible. Run once at init, this is  |
//| what turns "the EA is attached but nothing happens" into a named |
//| reason in the journal.                                           |
//+------------------------------------------------------------------+
bool DescribeAndValidateSymbol(const string symbol)
  {
   int    digits   = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double point    = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double tickSize = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickVal  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double contract = SymbolInfoDouble(symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   double minLot   = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maxLot   = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double lotStep  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double volLimit = SymbolInfoDouble(symbol, SYMBOL_VOLUME_LIMIT);
   long   stopsLvl = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long   freezeLvl= SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   long   tradeMode= SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE);
   long   exeMode  = SymbolInfoInteger(symbol, SYMBOL_TRADE_EXEMODE);
   long   fillMode = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   long   spreadPts= SymbolInfoInteger(symbol, SYMBOL_SPREAD);

   string curBase  = SymbolInfoString(symbol, SYMBOL_CURRENCY_BASE);
   string curProf  = SymbolInfoString(symbol, SYMBOL_CURRENCY_PROFIT);
   string curAcct  = AccountInfoString(ACCOUNT_CURRENCY);

   PrintFormat("[Broker] %s contract specification:", symbol);
   PrintFormat("   digits %d, point %.5f, tick size %.5f, tick value %.5f %s",
               digits, point, tickSize, tickVal, curAcct);
   PrintFormat("   contract size %.2f, base %s, profit %s, account %s",
               contract, curBase, curProf, curAcct);
   PrintFormat("   volume  min %.2f  max %.2f  step %.2f  limit %.2f",
               minLot, maxLot, lotStep, volLimit);
   PrintFormat("   stops level %d pts (%.2f price), freeze level %d pts (%.2f price)",
               (int)stopsLvl, stopsLvl * point, (int)freezeLvl, freezeLvl * point);
   PrintFormat("   current spread %d pts (%.2f price)", (int)spreadPts, spreadPts * point);

   string fills = "";
   if((fillMode & SYMBOL_FILLING_FOK) != 0) fills += "FOK ";
   if((fillMode & SYMBOL_FILLING_IOC) != 0) fills += "IOC ";
   if(StringLen(fills) == 0) fills = "RETURN only";
   PrintFormat("   filling modes: %s | execution mode %d", fills, (int)exeMode);

   int errors = 0;

   if(tradeMode == SYMBOL_TRADE_MODE_DISABLED)
     {
      PrintFormat("[Broker] FATAL: trading is DISABLED for %s.", symbol);
      errors++;
     }
   else
      if(tradeMode == SYMBOL_TRADE_MODE_CLOSEONLY)
        {
         PrintFormat("[Broker] FATAL: %s is CLOSE-ONLY - no new positions can be opened.", symbol);
         errors++;
        }
      else
         if(tradeMode == SYMBOL_TRADE_MODE_LONGONLY)
            PrintFormat("[Broker] WARNING: %s is LONG-ONLY - every short signal will be rejected.", symbol);
         else
            if(tradeMode == SYMBOL_TRADE_MODE_SHORTONLY)
               PrintFormat("[Broker] WARNING: %s is SHORT-ONLY - every long signal will be rejected.", symbol);

   if(point <= 0.0)
     {
      Print("[Broker] FATAL: SYMBOL_POINT is zero - price maths is impossible.");
      errors++;
     }
   if(minLot <= 0.0 || lotStep <= 0.0)
     {
      Print("[Broker] FATAL: the broker reports no usable volume min/step.");
      errors++;
     }
   if(PointValuePerLot(symbol) <= 0.0)
     {
      Print("[Broker] FATAL: the money value of a point could not be derived - "
            "position sizing would be guesswork. Check that the symbol is fully "
            "subscribed in Market Watch.");
      errors++;
     }

   if(digits != 2)
      PrintFormat("[Broker] NOTE: %s is quoted to %d decimals. Every price-based input "
                  "(ATR bounds, spread limit) is in QUOTE CURRENCY, so it is unaffected, "
                  "but check your expectations.", symbol, digits);

   return (errors == 0);
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
