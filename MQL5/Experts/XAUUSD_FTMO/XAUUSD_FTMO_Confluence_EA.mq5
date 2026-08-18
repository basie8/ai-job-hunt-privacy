//+------------------------------------------------------------------+
//|                                  XAUUSD_FTMO_Confluence_EA.mq5   |
//|                                                                  |
//|  XAUUSD multi-indicator confluence EA built around the FTMO      |
//|  2-STEP evaluation rule set.                                     |
//|                                                                  |
//|  Trading timeframe  : M15 execution, H1 + H4 context             |
//|  Sessions           : London and the London/NY overlap           |
//|  Confluence         : 11 weighted components, see ConfluenceEngine|
//|  Exits              : partial at 1R, breakeven lock, ATR trail,  |
//|                       runner to 3R                               |
//|  News               : ForexFactory feed + MT5 economic calendar  |
//|  Compliance         : layered soft/hard daily and total guards   |
//|                                                                  |
//|  READ docs/STRATEGY.md BEFORE RUNNING THIS ON A PAID CHALLENGE.  |
//+------------------------------------------------------------------+
#property copyright "XAUUSD FTMO Confluence EA"
#property version   "1.00"
#property description "XAUUSD confluence EA with FTMO 2-step risk guards and a high-impact news blackout."

#include "Include/CoreDefs.mqh"
#include "Include/TimeZones.mqh"
#include "Include/NewsFilter.mqh"
#include "Include/RiskGuard.mqh"
#include "Include/ConfluenceEngine.mqh"
#include "Include/TradeExecutor.mqh"
#include "Include/Dashboard.mqh"

//+------------------------------------------------------------------+
//| INPUTS                                                           |
//+------------------------------------------------------------------+
input group "=== General ==="
input string          InpSymbolOverride      = "";        // Symbol (blank = chart symbol)
input ulong           InpMagic               = 20260818;  // Magic number
input int             InpSlippagePoints      = 40;        // Max slippage (points)
input bool            InpVerboseLog          = false;     // Verbose journal logging
input string          InpTradeComment        = "XFC";     // Order comment

input group "=== Timeframes ==="
input ENUM_TIMEFRAMES InpTfTrade             = PERIOD_M15; // Execution timeframe
input ENUM_TIMEFRAMES InpTfMid               = PERIOD_H1;  // Intermediate trend timeframe
input ENUM_TIMEFRAMES InpTfHigh              = PERIOD_H4;  // Macro regime timeframe

input group "=== FTMO account parameters ==="
input double          InpInitialCapital      = 0.0;   // Initial capital (0 = current balance)
input double          InpFtmoDailyLossPct    = 5.0;   // FTMO max DAILY loss %  (rule)
input double          InpFtmoMaxLossPct      = 10.0;  // FTMO max TOTAL loss %  (rule)
input double          InpProfitTargetPct     = 10.0;  // Phase target % (10 = Challenge, 5 = Verification)
input bool            InpStopAtTarget        = true;  // Stop trading once the target is hit
input bool            InpAutoCetOffset       = true;  // Derive the CE(S)T day boundary automatically
input int             InpCetOffsetHours      = 0;     // Manual: server time minus CE(S)T, in hours

input group "=== Risk guards (kept well inside the FTMO limits) ==="
input ENUM_RISK_MODE  InpRiskMode            = RISK_PERCENT_INITIAL; // Position sizing basis
input double          InpRiskPercent         = 0.50;  // Risk per trade %
input double          InpFixedLot            = 0.10;  // Fixed lot (RISK_FIXED_LOT only)
input double          InpSoftDailyLossPct    = 2.00;  // Stop opening trades at daily DD %
input double          InpHardDailyLossPct    = 3.00;  // Flatten everything at daily DD %
input double          InpSoftTotalLossPct    = 5.00;  // Stop opening trades at total DD %
input double          InpHardTotalLossPct    = 7.00;  // Flatten everything at total DD %
input int             InpMaxTradesPerDay     = 3;     // Max trades per day (0 = unlimited)
input int             InpMaxConsecLosses     = 3;     // Pause for the day after N losses in a row
input double          InpLossStreakFactor    = 0.60;  // Risk multiplier per extra consecutive loss
input int             InpMaxOpenPositions    = 1;     // Max simultaneous positions

input group "=== Exit management (the asymmetry engine) ==="
input double          InpSlAtrMult           = 1.60;  // Initial stop = ATR x this
input int             InpSwingLookback       = 12;    // Bars scanned for the structural stop
input double          InpSwingBufferAtr      = 0.25;  // Buffer beyond the swing, in ATR
input double          InpMinStopAtr          = 1.00;  // Minimum stop distance, in ATR
input double          InpMaxStopAtr          = 3.00;  // Maximum stop distance, in ATR
input double          InpTp1R                = 1.00;  // First target, in R
input double          InpTp2R                = 3.00;  // Runner target, in R
input bool            InpUsePartial          = true;  // Scale out at TP1
input double          InpPartialPct          = 50.0;  // % of the position closed at TP1
input double          InpBreakevenLockR      = 0.10;  // Stop parked this many R beyond entry
input bool            InpUseTrailing         = true;  // Trail the runner
input double          InpTrailStartR         = 1.50;  // Trail engages at this many R
input double          InpTrailAtrMult        = 2.00;  // Chandelier distance, in ATR
input int             InpTrailLookback       = 10;    // Bars for the chandelier extreme

input group "=== Confluence thresholds ==="
input double          InpScoreThreshold      = 66.0;  // Minimum score (0-100) to trade
input double          InpDominanceMargin     = 22.0;  // Winning side must lead by this much
input double          InpAdxMin              = 20.0;  // Minimum ADX (hard gate)
input double          InpMaxExtensionAtr     = 2.20;  // Max distance from the slow EMA, in ATR
input double          InpMinAtrPrice         = 1.20;  // Volatility floor, in PRICE (0 = off)
input double          InpMaxAtrPrice         = 14.00; // Volatility ceiling, in PRICE (0 = off)
input double          InpVolumeFactor        = 1.10;  // Signal-bar volume vs 20-bar average

input group "=== Indicator periods ==="
input int             InpEmaFastTrade        = 8;     // EMA fast, execution TF
input int             InpEmaSlowTrade        = 21;    // EMA slow, execution TF
input int             InpEmaFastMid          = 21;    // EMA fast, intermediate TF
input int             InpEmaSlowMid          = 50;    // EMA slow, intermediate TF
input int             InpEmaFastHigh         = 50;    // EMA fast, macro TF
input int             InpEmaSlowHigh         = 200;   // EMA slow, macro TF
input int             InpRsiPeriod           = 14;    // RSI period
input int             InpAdxPeriod           = 14;    // ADX period
input int             InpAtrPeriod           = 14;    // ATR period
input int             InpStochK              = 14;    // Stochastic %K
input int             InpStochD              = 3;     // Stochastic %D
input int             InpStochSlow           = 3;     // Stochastic slowing
input int             InpBandsPeriod         = 20;    // Bollinger period
input double          InpBandsDev            = 2.0;   // Bollinger deviations
input int             InpMacdFast            = 12;    // MACD fast EMA
input int             InpMacdSlow            = 26;    // MACD slow EMA
input int             InpMacdSignal          = 9;     // MACD signal

input group "=== Confluence weights (relative, need not sum to 100) ==="
input double          InpWRegime             = 12.0;  // H4 regime
input double          InpWMidTrend           = 12.0;  // H1 trend
input double          InpWFastTrend          = 10.0;  // Execution TF trend + trigger
input double          InpWAdx                = 12.0;  // ADX / DI
input double          InpWRsi                =  8.0;  // RSI zone
input double          InpWMacd               = 10.0;  // MACD
input double          InpWStoch              =  8.0;  // Stochastic
input double          InpWVwap               =  8.0;  // Daily VWAP
input double          InpWBands              =  6.0;  // Bollinger location
input double          InpWStructure          =  8.0;  // Pivot / previous-day range
input double          InpWVolume             =  6.0;  // Volume confirmation

input group "=== RSI zones ==="
input double          InpRsiBullLow          = 45.0;  // Bullish RSI zone, lower bound
input double          InpRsiBullHigh         = 78.0;  // Bullish RSI zone, upper bound
input double          InpRsiBearLow          = 22.0;  // Bearish RSI zone, lower bound
input double          InpRsiBearHigh         = 55.0;  // Bearish RSI zone, upper bound

input group "=== Time alignment ==="
input bool            InpUseManualGmtOffset  = false;     // Override the auto-detected server offset
input int             InpGmtOffsetHours      = 0;         // Manual server-GMT offset (hours)
input bool            InpReDetectOffset      = true;      // Re-check the offset while running (catches DST)

input group "=== Trading sessions ==="
input ENUM_SESSION_TIMEBASE InpSessionTimeBase = SESSION_TB_MARKET_LOCAL; // How the times below are read
input bool            InpUseAsiaSession      = false;     // Trade the Asian session
input string          InpAsiaStart           = "09:00";   // Asia start  (Tokyo local)
input string          InpAsiaEnd             = "15:00";   // Asia end    (Tokyo local)
input bool            InpUseLondonSession    = true;      // Trade the London session
input string          InpLondonStart         = "08:00";   // London start (London local)
input string          InpLondonEnd           = "12:00";   // London end   (London local)
input bool            InpUseNewYorkSession   = true;      // Trade the New York session
input string          InpNewYorkStart        = "08:00";   // New York start (New York local)
input string          InpNewYorkEnd          = "12:00";   // New York end   (New York local)
input bool            InpTradeMonday         = true;      // Trade Monday
input bool            InpTradeFriday         = true;      // Trade Friday
input string          InpFridayCutoff        = "15:00";   // Friday: no new trades after (GMT)
input bool            InpFlatBeforeWeekend   = true;      // Close everything before the weekend
input string          InpWeekendFlatTime     = "19:00";   // Friday flatten time (GMT)
input int             InpMaxSpreadPoints     = 45;        // Max spread to trade (points)
input int             InpMinMinutesBetween   = 45;        // Minimum minutes between entries

input group "=== Daily quota (the 'at least one trade a day' rule) ==="
input bool            InpUseDailyQuota       = true;      // Relax the threshold late in the day
input string          InpQuotaFromTime       = "14:30";   // Quota mode starts at (GMT)
input double          InpQuotaScoreThreshold = 58.0;      // Relaxed score threshold
input double          InpQuotaDominance      = 15.0;      // Relaxed dominance margin
input double          InpQuotaRiskFactor     = 0.60;      // Risk multiplier for quota trades

input group "=== News filter ==="
input ENUM_NEWS_SOURCE InpNewsSource         = NEWS_SRC_BOTH; // Calendar source
input string          InpNewsCurrencies      = "USD,XAU,ALL";  // Blackout currencies ("*" = every event)
input int             InpNewsMinutesBefore   = 30;       // Blackout starts N minutes before
input int             InpNewsMinutesAfter    = 30;       // Blackout ends N minutes after
input bool            InpNewsIncludeMedium   = false;    // Also block medium (orange) events
input bool            InpNewsFlattenBefore   = true;     // Close open trades before a blackout
input int             InpNewsFlattenLeadMin  = 5;        // Flatten this many minutes ahead
input int             InpNewsRefreshMinutes  = 240;      // Feed refresh interval
input string          InpNewsManualCsv       = "";       // Optional manual CSV in MQL5\Files

input group "=== Dashboard ==="
input bool            InpShowDashboard       = true;     // Show the on-chart panel
input int             InpDashX               = 12;       // Panel X
input int             InpDashY               = 24;       // Panel Y
input int             InpDashFontSize        = 9;        // Panel font size

//+------------------------------------------------------------------+
//| GLOBALS                                                          |
//+------------------------------------------------------------------+
CNewsFilter       g_news;
CRiskGuard        g_risk;
CConfluenceEngine g_conf;
CTradeExecutor    g_exec;
CDashboard        g_dash;

string   g_symbol       = "";
int      g_gmtOffsetSec = 0;      // server time = GMT + this
int      g_cetOffsetSec = 0;      // server time = CE(S)T + this (FTMO day boundary)
int      g_cetPendingSec = 0;     // CET offset waiting for a safe moment to apply
bool     g_cetPending   = false;
bool     g_offsetPlausible = true;
bool     g_offsetWarned = false;
string   g_activeSession = "";
datetime g_lastBarTime  = 0;
datetime g_lastEntryTime = 0;
datetime g_lastNewsRefresh = 0;
string   g_lastBlockReason = "";
bool     g_hardStopped  = false;

//--- per-position realised P/L accumulator, so partial closes do not
//--- corrupt the win / loss streak accounting
ulong    g_accPosId[];
double   g_accProfit[];
int      g_accCount = 0;

//+------------------------------------------------------------------+
int AccIndex(const ulong posId)
  {
   for(int i = 0; i < g_accCount; i++)
      if(g_accPosId[i] == posId)
         return i;
   return -1;
  }

//+------------------------------------------------------------------+
void AccAdd(const ulong posId, const double profit)
  {
   int idx = AccIndex(posId);
   if(idx < 0)
     {
      ArrayResize(g_accPosId, g_accCount + 1);
      ArrayResize(g_accProfit, g_accCount + 1);
      g_accPosId[g_accCount]  = posId;
      g_accProfit[g_accCount] = 0.0;
      idx = g_accCount;
      g_accCount++;
     }
   g_accProfit[idx] += profit;
  }

//+------------------------------------------------------------------+
void AccRemove(const int idx)
  {
   if(idx < 0 || idx >= g_accCount)
      return;
   for(int i = idx; i < g_accCount - 1; i++)
     {
      g_accPosId[i]  = g_accPosId[i + 1];
      g_accProfit[i] = g_accProfit[i + 1];
     }
   g_accCount--;
   ArrayResize(g_accPosId, g_accCount);
   ArrayResize(g_accProfit, g_accCount);
  }

//+------------------------------------------------------------------+
//| Session helpers                                                  |
//+------------------------------------------------------------------+
datetime UtcNow(void)
  {
   return TimeTradeServer() - (datetime)g_gmtOffsetSec;
  }

//+------------------------------------------------------------------+
//| A session boundary converted to broker-server minutes, using the |
//| DST state in force right now.                                    |
//+------------------------------------------------------------------+
int SessionMinute(const string hhmm, const ENUM_MARKET_TZ tz)
  {
   return TZ_SessionMinuteToServer(hhmm, InpSessionTimeBase, tz, g_gmtOffsetSec, UtcNow());
  }

//+------------------------------------------------------------------+
//| Times that are always interpreted as GMT regardless of the       |
//| session time base: the Friday cutoff, the weekend flatten, and   |
//| the daily-quota trigger. A fixed reference keeps these stable    |
//| across DST rather than drifting with a market clock.             |
//+------------------------------------------------------------------+
int GmtMinuteToServer(const string hhmm)
  {
   int m = ParseHHMM(hhmm);
   if(m < 0)
      return -1;
   m += g_gmtOffsetSec / 60;
   return ((m % 1440) + 1440) % 1440;
  }

//+------------------------------------------------------------------+
//| True when 'now' sits inside the named session.                   |
//+------------------------------------------------------------------+
bool InNamedSession(const datetime serverNow,
                    const bool enabled,
                    const string startTime,
                    const string endTime,
                    const ENUM_MARKET_TZ tz)
  {
   if(!enabled)
      return false;

   int a = SessionMinute(startTime, tz);
   int b = SessionMinute(endTime, tz);
   if(a < 0 || b < 0)
      return false;

   return InMinuteWindow(MinutesOfDay(serverNow), a, b);
  }

//+------------------------------------------------------------------+
//| Minutes until a session opens, or -1 when it is disabled.        |
//+------------------------------------------------------------------+
int MinutesUntilSession(const datetime serverNow,
                        const bool enabled,
                        const string startTime,
                        const ENUM_MARKET_TZ tz)
  {
   if(!enabled)
      return -1;

   int a = SessionMinute(startTime, tz);
   if(a < 0)
      return -1;

   int now = MinutesOfDay(serverNow);
   int diff = a - now;
   if(diff < 0)
      diff += 1440;
   return diff;
  }

//+------------------------------------------------------------------+
//| Name of the session that is open right now, or "" when none is.  |
//| Stateless, so the dashboard and the trade logic can never        |
//| disagree about which session it is.                              |
//+------------------------------------------------------------------+
string CurrentSessionName(const datetime serverNow)
  {
   if(InNamedSession(serverNow, InpUseLondonSession, InpLondonStart, InpLondonEnd, MARKET_TZ_LONDON))
      return "London";
   if(InNamedSession(serverNow, InpUseNewYorkSession, InpNewYorkStart, InpNewYorkEnd, MARKET_TZ_NEWYORK))
      return "New York";
   if(InNamedSession(serverNow, InpUseAsiaSession, InpAsiaStart, InpAsiaEnd, MARKET_TZ_TOKYO))
      return "Asia";
   return "";
  }

//+------------------------------------------------------------------+
bool InTradingSession(const datetime serverNow, string &why)
  {
   g_activeSession = "";

   MqlDateTime st;
   TimeToStruct(serverNow, st);

   if(st.day_of_week == 0 || st.day_of_week == 6)
     {
      why = "weekend";
      return false;
     }
   if(!InpTradeMonday && st.day_of_week == 1)
     {
      why = "Monday disabled";
      return false;
     }
   if(!InpTradeFriday && st.day_of_week == 5)
     {
      why = "Friday disabled";
      return false;
     }

   if(st.day_of_week == 5)
     {
      int cutoff = GmtMinuteToServer(InpFridayCutoff);
      if(cutoff >= 0 && MinutesOfDay(serverNow) >= cutoff)
        {
         why = "past the Friday cutoff";
         return false;
        }
     }

   g_activeSession = CurrentSessionName(serverNow);

   if(StringLen(g_activeSession) == 0)
     {
      why = "outside the trading sessions";
      return false;
     }

   why = "";
   return true;
  }

//+------------------------------------------------------------------+
//| Dashboard text: the open session, or the next one due.           |
//+------------------------------------------------------------------+
string SessionStatusText(const datetime serverNow)
  {
   string open = CurrentSessionName(serverNow);
   if(StringLen(open) > 0)
      return open + " (open)";

   int best = 100000;
   string bestName = "";

   int m = MinutesUntilSession(serverNow, InpUseLondonSession, InpLondonStart, MARKET_TZ_LONDON);
   if(m >= 0 && m < best) { best = m; bestName = "London"; }

   m = MinutesUntilSession(serverNow, InpUseNewYorkSession, InpNewYorkStart, MARKET_TZ_NEWYORK);
   if(m >= 0 && m < best) { best = m; bestName = "New York"; }

   m = MinutesUntilSession(serverNow, InpUseAsiaSession, InpAsiaStart, MARKET_TZ_TOKYO);
   if(m >= 0 && m < best) { best = m; bestName = "Asia"; }

   if(StringLen(bestName) == 0)
      return "no session enabled";

   return StringFormat("closed - %s in %dh%02dm", bestName, best / 60, best % 60);
  }

//+------------------------------------------------------------------+
bool ShouldFlattenForWeekend(const datetime serverNow)
  {
   if(!InpFlatBeforeWeekend)
      return false;
   MqlDateTime st;
   TimeToStruct(serverNow, st);
   if(st.day_of_week != 5)
      return false;
   int flat = GmtMinuteToServer(InpWeekendFlatTime);
   if(flat < 0)
      return false;
   return (MinutesOfDay(serverNow) >= flat);
  }

//+------------------------------------------------------------------+
double CurrentSpreadPoints(void)
  {
   double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
   double pt  = SymbolInfoDouble(g_symbol, SYMBOL_POINT);
   if(pt <= 0.0)
      return 0.0;
   return (ask - bid) / pt;
  }

//+------------------------------------------------------------------+
//| Prints every session window as it will actually be applied, in   |
//| broker server time. This is the line to check when trades appear |
//| at the wrong hour - it makes a bad offset obvious immediately.   |
//+------------------------------------------------------------------+
string SessionWindowText(const string label,
                         const bool enabled,
                         const string startTime,
                         const string endTime,
                         const ENUM_MARKET_TZ tz)
  {
   if(!enabled)
      return StringFormat("   %-9s disabled", label);

   int a = SessionMinute(startTime, tz);
   int b = SessionMinute(endTime, tz);
   if(a < 0 || b < 0)
      return StringFormat("   %-9s INVALID TIME FORMAT (%s - %s), expected HH:MM", label, startTime, endTime);

   string basis;
   if(InpSessionTimeBase == SESSION_TB_MARKET_LOCAL)
      basis = StringFormat("%s local %s-%s, currently %s",
                           TZ_MarketName(tz), startTime, endTime,
                           TZ_OffsetText(TZ_MarketUtcOffsetSeconds(tz, UtcNow())));
   else
      if(InpSessionTimeBase == SESSION_TB_GMT)
         basis = StringFormat("GMT %s-%s", startTime, endTime);
      else
         basis = StringFormat("server %s-%s", startTime, endTime);

   return StringFormat("   %-9s %02d:%02d-%02d:%02d server   (%s)",
                       label, a / 60, a % 60, b / 60, b % 60, basis);
  }

//+------------------------------------------------------------------+
void LogSessionAlignment(void)
  {
   Print("[Time] resolved session windows:");
   Print(SessionWindowText("Asia",     InpUseAsiaSession,    InpAsiaStart,    InpAsiaEnd,    MARKET_TZ_TOKYO));
   Print(SessionWindowText("London",   InpUseLondonSession,  InpLondonStart,  InpLondonEnd,  MARKET_TZ_LONDON));
   Print(SessionWindowText("New York", InpUseNewYorkSession, InpNewYorkStart, InpNewYorkEnd, MARKET_TZ_NEWYORK));

   int cutoff = GmtMinuteToServer(InpFridayCutoff);
   int flat   = GmtMinuteToServer(InpWeekendFlatTime);
   int quota  = GmtMinuteToServer(InpQuotaFromTime);

   if(cutoff >= 0)
      PrintFormat("   %-9s %02d:%02d server   (GMT %s)", "Fri stop", cutoff / 60, cutoff % 60, InpFridayCutoff);
   if(flat >= 0)
      PrintFormat("   %-9s %02d:%02d server   (GMT %s)", "Fri flat", flat / 60, flat % 60, InpWeekendFlatTime);
   if(quota >= 0 && InpUseDailyQuota)
      PrintFormat("   %-9s %02d:%02d server   (GMT %s)", "Quota",  quota / 60, quota % 60, InpQuotaFromTime);

   datetime utc = UtcNow();
   PrintFormat("[Time] DST state: Europe %s, US %s.",
               (TZ_IsEuSummerTime(utc) ? "SUMMER" : "standard"),
               (TZ_IsUsSummerTime(utc) ? "SUMMER" : "standard"));
  }

//+------------------------------------------------------------------+
//| TIME ALIGNMENT                                                   |
//|                                                                  |
//| Re-detects the broker's GMT offset and re-derives the CE(S)T day |
//| boundary. Called on init and from the timer, so a DST transition |
//| on the broker's clock is picked up while the EA is running       |
//| instead of silently shifting every session and news window by an |
//| hour until the next restart.                                     |
//+------------------------------------------------------------------+
void RefreshTimeAlignment(const bool firstRun)
  {
   bool plausible = true;
   int detected = TZ_DetectServerGmtOffset(InpGmtOffsetHours, InpUseManualGmtOffset, plausible);

   g_offsetPlausible = plausible;

   if(!plausible && !g_offsetWarned)
     {
      PrintFormat("[Time] WARNING: the server-GMT offset could not be detected reliably. "
                  "Falling back to the manual value (%+d h). Set InpUseManualGmtOffset=true "
                  "and InpGmtOffsetHours to your broker's real offset.", InpGmtOffsetHours);
      g_offsetWarned = true;
     }

   //--- GMT offset changed (DST transition, or a corrected clock)
   if(firstRun || detected != g_gmtOffsetSec)
     {
      int previous = g_gmtOffsetSec;
      g_gmtOffsetSec = detected;

      if(firstRun)
         PrintFormat("[Time] broker server clock is %s (offset %+.1f h).",
                     TZ_OffsetText(g_gmtOffsetSec), g_gmtOffsetSec / 3600.0);
      else
         PrintFormat("[Time] server-GMT offset changed %+.1f h -> %+.1f h. "
                     "Re-aligning sessions and re-parsing the news calendar.",
                     previous / 3600.0, g_gmtOffsetSec / 3600.0);

      // ForexFactory timestamps were converted to server time under the OLD
      // offset, so the table has to be rebuilt, not merely re-read
      g_news.SetGmtOffset(g_gmtOffsetSec);
      if(!firstRun)
         g_news.Refresh(true);
     }

   //--- CE(S)T day boundary used by the FTMO daily-loss rule
   int cetTarget;
   if(InpAutoCetOffset)
     {
      int cetFromUtc = TZ_MarketUtcOffsetSeconds(MARKET_TZ_CET, UtcNow());
      cetTarget = g_gmtOffsetSec - cetFromUtc;      // server time minus CE(S)T
     }
   else
      cetTarget = InpCetOffsetHours * 3600;

   if(firstRun)
     {
      g_cetOffsetSec = cetTarget;
      g_cetPending   = false;
      PrintFormat("[Time] FTMO day boundary: server time minus CE(S)T = %+.1f h%s.",
                  g_cetOffsetSec / 3600.0, (InpAutoCetOffset ? " (auto)" : " (manual)"));
      return;
     }

   if(cetTarget != g_cetOffsetSec)
     {
      // Moving the day boundary mid-session would reset today's loss counter
      // and trade count, so it only happens when nothing is at stake.
      bool safe = (g_risk.TradesToday() == 0 && !g_exec.HasOpenPosition());

      if(safe)
        {
         PrintFormat("[Time] CE(S)T day boundary shifted %+.1f h -> %+.1f h (applied).",
                     g_cetOffsetSec / 3600.0, cetTarget / 3600.0);
         g_cetOffsetSec = cetTarget;
         g_risk.SetCetOffset(g_cetOffsetSec);
         g_cetPending = false;
        }
      else
        {
         if(!g_cetPending || g_cetPendingSec != cetTarget)
            PrintFormat("[Time] CE(S)T day boundary shift to %+.1f h deferred - "
                        "a position or today's trade count is still open.", cetTarget / 3600.0);
         g_cetPendingSec = cetTarget;
         g_cetPending    = true;
        }
     }
   else
      g_cetPending = false;
  }

//+------------------------------------------------------------------+
//| OnInit                                                           |
//+------------------------------------------------------------------+
int OnInit(void)
  {
   g_symbol = (StringLen(InpSymbolOverride) > 0 ? InpSymbolOverride : _Symbol);

   if(!SymbolSelect(g_symbol, true))
     {
      PrintFormat("FATAL: symbol %s could not be selected.", g_symbol);
      return INIT_FAILED;
     }

   string upper = g_symbol;
   StringToUpper(upper);
   if(StringFind(upper, "XAU") < 0 && StringFind(upper, "GOLD") < 0)
      PrintFormat("WARNING: %s does not look like gold. Every default in this EA is tuned for XAUUSD.", g_symbol);

   // resolved after the news filter is constructed but before it initialises,
   // because the FF parser needs the offset to convert its timestamps
   bool plausible = true;
   g_gmtOffsetSec = TZ_DetectServerGmtOffset(InpGmtOffsetHours, InpUseManualGmtOffset, plausible);
   g_offsetPlausible = plausible;

   //--- confluence engine
   g_conf.SetPeriods(InpEmaFastTrade, InpEmaSlowTrade,
                     InpEmaFastMid, InpEmaSlowMid,
                     InpEmaFastHigh, InpEmaSlowHigh,
                     InpRsiPeriod, InpAdxPeriod, InpAtrPeriod,
                     InpStochK, InpStochD, InpStochSlow,
                     InpBandsPeriod, InpBandsDev,
                     InpMacdFast, InpMacdSlow, InpMacdSignal);

   g_conf.SetThresholds(InpAdxMin,
                        InpRsiBullLow, InpRsiBullHigh,
                        InpRsiBearLow, InpRsiBearHigh,
                        InpMaxExtensionAtr,
                        InpMinAtrPrice, InpMaxAtrPrice,
                        InpVolumeFactor);

   g_conf.SetWeights(InpWRegime, InpWMidTrend, InpWFastTrend, InpWAdx,
                     InpWRsi, InpWMacd, InpWStoch, InpWVwap,
                     InpWBands, InpWStructure, InpWVolume);

   if(!g_conf.Init(g_symbol, InpTfTrade, InpTfMid, InpTfHigh))
      return INIT_FAILED;

   //--- CE(S)T day boundary, derived from the server offset unless overridden
   if(InpAutoCetOffset)
      g_cetOffsetSec = g_gmtOffsetSec - TZ_MarketUtcOffsetSeconds(MARKET_TZ_CET, UtcNow());
   else
      g_cetOffsetSec = InpCetOffsetHours * 3600;

   //--- risk guard
   if(!g_risk.Init(g_symbol, InpMagic, InpInitialCapital,
                   InpFtmoDailyLossPct, InpFtmoMaxLossPct,
                   InpSoftDailyLossPct, InpHardDailyLossPct,
                   InpSoftTotalLossPct, InpHardTotalLossPct,
                   InpProfitTargetPct, InpStopAtTarget,
                   InpMaxTradesPerDay, InpMaxConsecLosses,
                   InpLossStreakFactor, g_cetOffsetSec))
      return INIT_FAILED;

   //--- execution
   if(!g_exec.Init(g_symbol, InpTfTrade, InpMagic, InpSlippagePoints, InpVerboseLog))
      return INIT_FAILED;

   g_exec.SetManagement(InpPartialPct, InpBreakevenLockR, InpTrailStartR,
                        InpTrailAtrMult, InpTrailLookback,
                        InpUsePartial, InpUseTrailing);

   //--- news
   g_news.Init(InpNewsSource, InpNewsCurrencies,
               InpNewsMinutesBefore, InpNewsMinutesAfter,
               InpNewsIncludeMedium, g_gmtOffsetSec,
               InpNewsRefreshMinutes, InpNewsManualCsv, InpVerboseLog);

   if(InpNewsSource == NEWS_SRC_OFF)
      Print("WARNING: the news filter is OFF. FTMO forbids opening or closing trades around high-impact news.");

   //--- report the resolved alignment and prime the re-detection state
   RefreshTimeAlignment(true);
   LogSessionAlignment();

   //--- dashboard
   g_dash.Init(InpShowDashboard, InpDashX, InpDashY, InpDashFontSize);

   EventSetTimer(20);

   Print("=== XAUUSD FTMO Confluence EA initialised ===");
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   g_dash.Destroy();
   PrintFormat("=== EA stopped (reason %d) ===", reason);
  }

//+------------------------------------------------------------------+
//| OnTimer - housekeeping only, never trading decisions             |
//+------------------------------------------------------------------+
void OnTimer(void)
  {
   if(InpReDetectOffset || g_cetPending)
      RefreshTimeAlignment(false);

   g_news.Refresh(false);
   UpdateDashboard();
  }

//+------------------------------------------------------------------+
//| OnTick                                                           |
//+------------------------------------------------------------------+
void OnTick(void)
  {
   datetime now = TimeTradeServer();

   g_risk.OnTick(now);

   double atr = g_conf.AtrHandleValue(1);

   //--- 1. always manage what is already open, whatever the guards say
   g_exec.Manage(atr);

   //--- 2. compliance guards outrank everything
   ENUM_GUARD_ACTION action = g_risk.Evaluate();

   if(action == GUARD_HARD_FLAT)
     {
      if(g_exec.HasOpenPosition())
         g_exec.CloseAll(g_risk.LastReason());
      if(!g_hardStopped)
        {
         PrintFormat("[GUARD] %s", g_risk.LastReason());
         g_hardStopped = true;
        }
      g_lastBlockReason = g_risk.LastReason();
      return;
     }
   g_hardStopped = false;

   //--- 3. weekend flat
   if(ShouldFlattenForWeekend(now))
     {
      if(g_exec.HasOpenPosition())
         g_exec.CloseAll("weekend flat");
      g_lastBlockReason = "weekend flat";
      return;
     }

   //--- 4. news blackout
   bool blackout = g_news.IsBlackout(now);

   if(InpNewsFlattenBefore && g_exec.HasOpenPosition())
     {
      // FTMO forbids CLOSING inside the window too, so exit early or not at all
      if(!blackout && g_news.BlackoutStartsWithin(now, InpNewsFlattenLeadMin))
        {
         g_exec.CloseAll("flattening ahead of a high-impact release");
         g_lastBlockReason = "pre-news flat";
         return;
        }
     }

   if(blackout)
     {
      g_lastBlockReason = "news blackout: " + g_news.BlackoutTitle();
      return;
     }

   if(action == GUARD_SOFT_HALT)
     {
      g_lastBlockReason = g_risk.LastReason();
      return;
     }

   //--- 5. session
   string why = "";
   if(!InTradingSession(now, why))
     {
      g_lastBlockReason = why;
      return;
     }

   //--- 6. one position at a time
   if(g_exec.OpenPositions() >= InpMaxOpenPositions)
     {
      g_lastBlockReason = "position already open";
      return;
     }

   //--- 7. spacing between entries
   if(InpMinMinutesBetween > 0 && g_lastEntryTime > 0)
     {
      if((now - g_lastEntryTime) < InpMinMinutesBetween * 60)
        {
         g_lastBlockReason = "entry spacing";
         return;
        }
     }

   //--- 8. spread
   double spread = CurrentSpreadPoints();
   if(InpMaxSpreadPoints > 0 && spread > InpMaxSpreadPoints)
     {
      g_lastBlockReason = StringFormat("spread %.0f > %d", spread, InpMaxSpreadPoints);
      return;
     }

   //--- 9. one evaluation per closed bar
   datetime barTime = iTime(g_symbol, InpTfTrade, 0);
   if(barTime == g_lastBarTime)
      return;
   g_lastBarTime = barTime;

   //--- 10. quota mode: relax the bar late in the day if nothing has traded
   double threshold = InpScoreThreshold;
   double margin    = InpDominanceMargin;
   double riskMult  = 1.0;
   bool   quotaMode = false;

   if(InpUseDailyQuota && g_risk.TradesToday() == 0)
     {
      int quotaFrom = GmtMinuteToServer(InpQuotaFromTime);
      if(quotaFrom >= 0 && MinutesOfDay(now) >= quotaFrom)
        {
         threshold = InpQuotaScoreThreshold;
         margin    = InpQuotaDominance;
         riskMult  = InpQuotaRiskFactor;
         quotaMode = true;
        }
     }

   //--- 11. evaluate the confluence stack
   SignalSnapshot snap;
   ENUM_SIGNAL_DIR dir = g_conf.Evaluate(threshold, margin, snap);

   if(dir == SIGNAL_NONE)
     {
      g_lastBlockReason = snap.reason;
      if(InpVerboseLog)
         PrintFormat("[Signal] %s", snap.reason);
      return;
     }

   //--- 12. build the stop and targets
   if(!g_conf.BuildLevels(dir, snap.atr, InpSlAtrMult, InpSwingLookback,
                          InpSwingBufferAtr, InpMinStopAtr, InpMaxStopAtr,
                          InpTp1R, InpTp2R, snap))
     {
      g_lastBlockReason = "stop construction failed";
      return;
     }

   //--- 13. size it
   double lots = g_risk.LotsForRisk(InpRiskPercent * riskMult, snap.riskDistance,
                                    InpRiskMode, InpFixedLot);
   if(lots <= 0.0)
     {
      g_lastBlockReason = "risk budget exhausted or lot below the broker minimum";
      PrintFormat("[Trade] skipped: %s", g_lastBlockReason);
      return;
     }

   //--- 14. the runner carries TP2; TP1 is handled by the partial logic
   double tp = (InpUsePartial ? snap.tp2 : snap.tp1);

   string comment = StringFormat("%s %s%.0f", InpTradeComment,
                                 (quotaMode ? "Q" : "S"),
                                 (dir == SIGNAL_BUY ? snap.bullScore : snap.bearScore));

   ulong ticket = g_exec.OpenTrade(dir, lots, snap.stop, tp, comment);

   if(ticket > 0)
     {
      g_risk.RegisterOpen();
      g_lastEntryTime = now;
      g_lastBlockReason = "";

      PrintFormat("[Trade] %s | %s | ATR=%.2f risk=%.2f lots=%.2f %s",
                  (dir == SIGNAL_BUY ? "BUY" : "SELL"),
                  snap.reason, snap.atr, snap.riskDistance, lots,
                  (quotaMode ? "[QUOTA MODE - reduced size]" : ""));
      PrintFormat("[Trade] breakdown: %s", g_conf.BreakdownText());
     }

   UpdateDashboard();
  }

//+------------------------------------------------------------------+
//| OnTradeTransaction - streak and P/L accounting                   |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD)
      return;

   ulong dealTicket = trans.deal;
   if(dealTicket == 0)
      return;

   if(!HistoryDealSelect(dealTicket))
      return;

   if(HistoryDealGetString(dealTicket, DEAL_SYMBOL) != g_symbol)
      return;
   if((ulong)HistoryDealGetInteger(dealTicket, DEAL_MAGIC) != InpMagic)
      return;

   ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY)
      return;

   ulong posId = (ulong)HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID);

   double profit = HistoryDealGetDouble(dealTicket, DEAL_PROFIT)
                   + HistoryDealGetDouble(dealTicket, DEAL_SWAP)
                   + HistoryDealGetDouble(dealTicket, DEAL_COMMISSION);

   AccAdd(posId, profit);

   // the position is only finished when it no longer exists
   if(!PositionSelectByTicket(posId))
     {
      int idx = AccIndex(posId);
      if(idx >= 0)
        {
         double total = g_accProfit[idx];
         g_risk.RegisterClosedTrade(total);
         PrintFormat("[Result] position #%I64u closed for %.2f | today W/L %d/%d | streak %d",
                     posId, total, g_risk.WinsToday(), g_risk.LossesToday(),
                     g_risk.ConsecutiveLosses());
         AccRemove(idx);
        }
     }
  }

//+------------------------------------------------------------------+
//| Dashboard                                                        |
//+------------------------------------------------------------------+
void UpdateDashboard(void)
  {
   if(!InpShowDashboard)
      return;

   datetime now = TimeTradeServer();

   double dailyDd = g_risk.DailyDrawdownPct();
   double totalDd = g_risk.TotalDrawdownPct();
   double profit  = g_risk.ProfitPct();

   color ddColor = clrLimeGreen;
   if(dailyDd > InpSoftDailyLossPct * 0.5)
      ddColor = clrGold;
   if(dailyDd >= InpSoftDailyLossPct)
      ddColor = clrTomato;

   color profitColor = (profit >= 0.0 ? clrLimeGreen : clrTomato);

   g_dash.Begin();
   g_dash.Row("XAUUSD FTMO CONFLUENCE EA", clrDeepSkyBlue);
   g_dash.Row(StringFormat("%s  %s  server %s", g_symbol,
                           EnumToString(InpTfTrade),
                           TimeToString(now, TIME_MINUTES)), clrGainsboro);
   g_dash.Separator();

   g_dash.Row(StringFormat("Progress   %+.2f%%  of %.2f%% target", profit, InpProfitTargetPct), profitColor);
   g_dash.Row(StringFormat("Daily DD   %.2f%%  (soft %.2f / hard %.2f)", dailyDd,
                           InpSoftDailyLossPct, InpHardDailyLossPct), ddColor);
   g_dash.Row(StringFormat("Total DD   %.2f%%  (soft %.2f / hard %.2f)", totalDd,
                           InpSoftTotalLossPct, InpHardTotalLossPct),
              (totalDd >= InpSoftTotalLossPct ? clrTomato : clrGainsboro));
   g_dash.Row(StringFormat("Trades     %d today, %d/%d W/L, streak %d, %d trading days",
                           g_risk.TradesToday(), g_risk.WinsToday(), g_risk.LossesToday(),
                           g_risk.ConsecutiveLosses(), g_risk.TradingDays()), clrGainsboro);
   g_dash.Row(StringFormat("Risk       %.2f%% x %.2f streak factor",
                           InpRiskPercent, g_risk.RiskFactor()), clrGainsboro);
   g_dash.Separator();

   g_dash.Row(StringFormat("ATR %.2f   ADX %.1f   RSI %.1f   VWAP %.2f",
                           g_conf.Atr(), g_conf.Adx(), g_conf.Rsi(), g_conf.Vwap()), clrGainsboro);
   g_dash.Row(StringFormat("Spread %.0f pts   Positions %d",
                           CurrentSpreadPoints(), g_exec.OpenPositions()), clrGainsboro);
   g_dash.Separator();

   string dstText = StringFormat("EU %s / US %s",
                                 (TZ_IsEuSummerTime(UtcNow()) ? "DST" : "std"),
                                 (TZ_IsUsSummerTime(UtcNow()) ? "DST" : "std"));
   g_dash.Row(StringFormat("Clock      server %s | CET %+.0fh | %s",
                           TZ_OffsetText(g_gmtOffsetSec),
                           g_cetOffsetSec / 3600.0, dstText),
              (g_offsetPlausible ? clrGainsboro : clrTomato));
   g_dash.Row("Session    " + SessionStatusText(now),
              (StringLen(CurrentSessionName(now)) > 0 ? clrLimeGreen : clrGainsboro));
   g_dash.Separator();

   bool blackout = g_news.IsBlackout(now);
   if(InpNewsSource == NEWS_SRC_OFF)
      g_dash.Row("News       FILTER OFF - not FTMO compliant", clrRed);
   else
      if(blackout)
         g_dash.Row("News       BLACKOUT: " + g_news.BlackoutTitle(), clrRed);
      else
         g_dash.Row(StringFormat("News       %d events | next: %s",
                                 g_news.EventCount(), g_news.NextEventText(now)), clrGainsboro);

   string state = (StringLen(g_lastBlockReason) > 0 ? g_lastBlockReason : "hunting for a setup");
   g_dash.Row("State      " + state, (g_hardStopped ? clrRed : clrGold));
   g_dash.Row("Positions  " + g_exec.StateText(), clrGainsboro);

   ChartRedraw();
  }
//+------------------------------------------------------------------+
