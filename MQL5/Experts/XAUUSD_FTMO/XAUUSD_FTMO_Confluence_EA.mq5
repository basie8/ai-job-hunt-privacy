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

//--- Bump on every release. Printed at init and written into the diagnostic
//--- file, so "am I running the build I just compiled?" is never a guess.
#define XFC_BUILD_ID "dev"   // replaced with a content hash by tools/build_single_file.py

#include "Include/CoreDefs.mqh"
#include "Include/TimeZones.mqh"
#include "Include/NewsFilter.mqh"
#include "Include/RiskGuard.mqh"
#include "Include/ConfluenceEngine.mqh"
#include "Include/TradeExecutor.mqh"
#include "Include/Statistics.mqh"
#include "Include/Dashboard.mqh"

//+------------------------------------------------------------------+
//| INCLUDE VERSION CHECK                                            |
//|                                                                  |
//| Every header stamps a version token. If one is missing, the      |
//| Include folder is older than this .mq5 - the usual cause being a |
//| partial copy into MQL5/Experts/. Without this check that shows   |
//| up as dozens of "undeclared identifier" errors pointing at the   |
//| wrong file. With it, the FIRST error names the stale header.     |
//|                                                                  |
//| Fix: copy the ENTIRE XAUUSD_FTMO folder, Include/ included.      |
//+------------------------------------------------------------------+
#ifndef XFC_V_COREDEFS_3
   int STALE_INCLUDE__CoreDefs_mqh__RECOPY_THE_WHOLE_Include_FOLDER = XFC_V_COREDEFS_3_IS_MISSING;
#endif
#ifndef XFC_V_TIMEZONES_1
   int STALE_INCLUDE__TimeZones_mqh__RECOPY_THE_WHOLE_Include_FOLDER = XFC_V_TIMEZONES_1_IS_MISSING;
#endif
#ifndef XFC_V_NEWSFILTER_1
   int STALE_INCLUDE__NewsFilter_mqh__RECOPY_THE_WHOLE_Include_FOLDER = XFC_V_NEWSFILTER_1_IS_MISSING;
#endif
#ifndef XFC_V_RISKGUARD_2
   int STALE_INCLUDE__RiskGuard_mqh__RECOPY_THE_WHOLE_Include_FOLDER = XFC_V_RISKGUARD_2_IS_MISSING;
#endif
#ifndef XFC_V_CONFLUENCE_3
   int STALE_INCLUDE__ConfluenceEngine_mqh__RECOPY_THE_WHOLE_Include_FOLDER = XFC_V_CONFLUENCE_3_IS_MISSING;
#endif
#ifndef XFC_V_TRADEEXEC_3
   int STALE_INCLUDE__TradeExecutor_mqh__RECOPY_THE_WHOLE_Include_FOLDER = XFC_V_TRADEEXEC_3_IS_MISSING;
#endif
#ifndef XFC_V_STATISTICS_2
   int STALE_INCLUDE__Statistics_mqh__RECOPY_THE_WHOLE_Include_FOLDER = XFC_V_STATISTICS_2_IS_MISSING;
#endif
#ifndef XFC_V_DASHBOARD_2
   int STALE_INCLUDE__Dashboard_mqh__RECOPY_THE_WHOLE_Include_FOLDER = XFC_V_DASHBOARD_2_IS_MISSING;
#endif

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
input double          InpMaxMarginPct        = 80.0;  // Max % of free margin one trade may use

input group "=== Exit management (the asymmetry engine) ==="
input double          InpSlAtrMult           = 1.10;  // Initial stop = ATR x this
input int             InpSwingLookback       = 12;    // Bars scanned for the structural stop
input double          InpSwingBufferAtr      = 0.25;  // Buffer beyond the swing, in ATR
input double          InpMinStopAtr          = 1.00;  // Minimum stop distance, in ATR
input double          InpMaxStopAtr          = 3.00;  // Maximum stop distance, in ATR
input double          InpTp1R                = 1.00;  // First target, in R
input double          InpTp2R                = 2.20;  // Runner target, in R
input bool            InpUsePartial          = true;  // Scale out at TP1
input double          InpPartialPct          = 40.0;  // % of the position closed at TP1
input double          InpBreakevenLockR      = 0.05;  // Stop parked this many R beyond entry
input bool            InpUseTrailing         = true;  // Trail the runner
input double          InpTrailStartR         = 1.05;  // Trail engages at this many R
input double          InpTrailAtrMult        = 1.20;  // Chandelier distance, in ATR
input double          InpTrailStepPrice      = 0.20;  // Min stop improvement before a modify (USD)
input int             InpTrailLookback       = 10;    // Bars for the chandelier extreme

input group "=== Confluence thresholds ==="
input double          InpScoreThreshold      = 72.0;  // Minimum score (0-100) to trade
input double          InpDominanceMargin     = 30.0;  // Winning side must lead by this much
input double          InpAdxMin              = 20.0;  // Minimum ADX (hard gate)
input double          InpMaxExtensionAtr     = 2.20;  // Max distance from the slow EMA, in ATR
input ENUM_ATR_BAND_MODE InpAtrBandMode      = ATR_BAND_RELATIVE; // How the volatility band is measured
input double          InpAtrMinRelative      = 0.60;  // RELATIVE: min ATR / its own average
input double          InpAtrMaxRelative      = 2.50;  // RELATIVE: max ATR / its own average
input int             InpAtrAvgPeriod        = 100;   // RELATIVE: bars in the ATR average
input double          InpAtrMinPercent       = 0.020; // PERCENT: min ATR as % of price
input double          InpAtrMaxPercent       = 0.350; // PERCENT: max ATR as % of price
input double          InpMinAtrPrice         = 1.20;  // ABSOLUTE: floor in price (0 = off)
input double          InpMaxAtrPrice         = 14.00; // ABSOLUTE: ceiling in price (0 = off)
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
input double          InpMaxSpreadPrice      = 0.50;      // Max spread to trade, in QUOTE CURRENCY (USD)
input int             InpMinMinutesBetween   = 45;        // Minimum minutes between entries

input group "=== Daily quota (the 'at least one trade a day' rule) ==="
input bool            InpUseDailyQuota       = true;      // Relax the threshold late in the day
input string          InpQuotaFromTime       = "14:30";   // Quota mode starts at (GMT)
input double          InpQuotaScoreThreshold = 62.0;      // Relaxed score threshold
input double          InpQuotaDominance      = 20.0;      // Relaxed dominance margin
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

input group "=== Aurum console ==="
input bool            InpShowDashboard       = true;     // Show the on-chart console
input int             InpDashX               = 14;       // Console X
input int             InpDashY               = 24;       // Console Y
input int             InpDashWidth           = 360;      // Console width (pixels)
input int             InpDashFontSize        = 8;        // Console font size
input bool            InpShowParamsBlock     = false;    // Start with the parameter block open
input bool            InpShowMetricsBlock    = true;     // Start with the metrics block open
input bool            InpRebuildStatsOnInit  = true;     // Rebuild metrics from account history
input bool            InpWriteDiagnosticFile = true;     // Write a diagnostics CSV on exit
input string          InpRunTag              = "";       // Run label - names the diagnostics file
input int             InpStatsHistoryDays    = 90;       // How far back to rebuild (days)

//+------------------------------------------------------------------+
//| GLOBALS                                                          |
//+------------------------------------------------------------------+
CNewsFilter       g_news;
CRiskGuard        g_risk;
CConfluenceEngine g_conf;
CTradeExecutor    g_exec;
CStatistics       g_stats;
CDashboard        g_dash;

string   g_symbol       = "";
int      g_gmtOffsetSec = 0;      // server time = GMT + this
int      g_cetOffsetSec = 0;      // server time = CE(S)T + this (FTMO day boundary)
int      g_cetPendingSec = 0;     // CET offset waiting for a safe moment to apply
bool     g_cetPending   = false;
bool     g_offsetPlausible = true;
bool     g_offsetWarned = false;
string   g_activeSession = "";
ENUM_EA_STATUS g_status       = EA_STATUS_ACTIVE;
string   g_statusDetail       = "";
bool     g_showParams         = false;
bool     g_showMetrics        = true;

//--- "why am I not trading" histogram. Counted since start and for today,
//--- so a silent EA always explains itself instead of just sitting there.
long     g_vetoStatus[9];
long     g_vetoStatusDay[9];
long     g_vetoGate[GATE_REASON_COUNT];
long     g_vetoGateDay[GATE_REASON_COUNT];
long     g_barsSeen      = 0;
long     g_barsSeenDay   = 0;
long     g_ticksSeen     = 0;   // ticks the EA was called on at all
long     g_ticksSeenDay  = 0;
datetime g_lastSummary   = 0;
datetime g_vetoDayStamp  = 0;
datetime g_lastBarTime  = 0;
datetime g_lastEntryTime = 0;
datetime g_lastNewsRefresh = 0;
string   g_lastBlockReason = "";
bool     g_hardStopped  = false;

//--- per-position realised P/L accumulator, so partial closes do not
//--- corrupt the win / loss streak accounting
ulong    g_accPosId[];
double   g_accProfit[];
double   g_accRisk[];          // risk money at entry, for R-multiple stats
datetime g_accSeeded[];        // when the entry was created, for the orphan sweep
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
      ArrayResize(g_accRisk, g_accCount + 1);
      ArrayResize(g_accSeeded, g_accCount + 1);
      g_accPosId[g_accCount]  = posId;
      g_accProfit[g_accCount] = 0.0;
      g_accRisk[g_accCount]   = 0.0;
      g_accSeeded[g_accCount] = TimeTradeServer();
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
      g_accRisk[i]   = g_accRisk[i + 1];
      g_accSeeded[i] = g_accSeeded[i + 1];
     }
   g_accCount--;
   ArrayResize(g_accPosId, g_accCount);
   ArrayResize(g_accProfit, g_accCount);
   ArrayResize(g_accRisk, g_accCount);
   ArrayResize(g_accSeeded, g_accCount);
  }

//+------------------------------------------------------------------+
//| Records the money at risk when a position is opened, so the      |
//| console can report expectancy in R once the trade closes.        |
//+------------------------------------------------------------------+
void AccSetRisk(const ulong posId, const double riskMoney)
  {
   AccAdd(posId, 0.0);
   int idx = AccIndex(posId);
   if(idx >= 0)
      g_accRisk[idx] = riskMoney;
  }

//+------------------------------------------------------------------+
//| Drops accumulator entries whose position no longer exists and    |
//| which never recorded an exit deal.                               |
//|                                                                  |
//| That combination only arises if the position ticket resolved at  |
//| entry did not match the id the deal history reports - rare, but  |
//| without this sweep the entry would live for the whole session.   |
//| The five minute grace period keeps a normal close, where the     |
//| position disappears a moment before its deal arrives, safe.      |
//+------------------------------------------------------------------+
void AccSweep(void)
  {
   datetime now = TimeTradeServer();

   for(int i = g_accCount - 1; i >= 0; i--)
     {
      if(g_accProfit[i] != 0.0)
         continue;                          // exit deals are arriving, leave it
      if((now - g_accSeeded[i]) < 300)
         continue;                          // inside the grace period
      if(PositionSelectByTicket(g_accPosId[i]))
         continue;                          // still open

      PrintFormat("[Stats] dropped orphaned tracking entry for position #%I64u.", g_accPosId[i]);
      AccRemove(i);
     }
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
//+------------------------------------------------------------------+
//| Spread in QUOTE CURRENCY, not points.                            |
//|                                                                  |
//| A points-based limit is a trap on gold: brokers quote XAUUSD to  |
//| either 2 or 3 decimals, so the same 30-cent spread reads as 30   |
//| points on one feed and 300 on another. A limit tuned on a 2-digit|
//| feed silently blocks every trade on a 3-digit one. Measuring in  |
//| price makes the setting mean the same thing everywhere.          |
//+------------------------------------------------------------------+
double CurrentSpreadPrice(void)
  {
   double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
   if(ask <= 0.0 || bid <= 0.0)
      return 0.0;
   return (ask - bid);
  }

//+------------------------------------------------------------------+
double CurrentSpreadPoints(void)
  {
   double pt = SymbolInfoDouble(g_symbol, SYMBOL_POINT);
   if(pt <= 0.0)
      return 0.0;
   return CurrentSpreadPrice() / pt;
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
//| Input validation.                                                |
//|                                                                  |
//| Every check here is a setting that would otherwise fail silently |
//| - the EA would attach, report no error, and simply never trade   |
//| or trade with broken geometry. Failing init with a named reason  |
//| is far better than a quiet no-op on a paid challenge.            |
//+------------------------------------------------------------------+
bool ValidateInputs(void)
  {
   int errors = 0;

   //--- confluence gate must be reachable
   if(InpScoreThreshold <= 0.0 || InpScoreThreshold > 100.0)
     {
      PrintFormat("INPUT ERROR: InpScoreThreshold (%.1f) must be in 0-100.", InpScoreThreshold);
      errors++;
     }
   if(InpDominanceMargin < 0.0 || InpDominanceMargin > 100.0)
     {
      PrintFormat("INPUT ERROR: InpDominanceMargin (%.1f) must be in 0-100.", InpDominanceMargin);
      errors++;
     }
   if(InpScoreThreshold + InpDominanceMargin > 200.0)
     {
      Print("INPUT ERROR: InpScoreThreshold + InpDominanceMargin can never be satisfied.");
      errors++;
     }

   //--- weights must not all be zero, or every score is 0
   double weightSum = InpWRegime + InpWMidTrend + InpWFastTrend + InpWAdx + InpWRsi
                      + InpWMacd + InpWStoch + InpWVwap + InpWBands + InpWStructure + InpWVolume;
   if(weightSum <= 0.0)
     {
      Print("INPUT ERROR: all confluence weights are zero - no signal can ever be produced.");
      errors++;
     }

   //--- trade geometry
   if(InpTp2R <= InpTp1R)
     {
      PrintFormat("INPUT ERROR: InpTp2R (%.2f) must exceed InpTp1R (%.2f).", InpTp2R, InpTp1R);
      errors++;
     }
   if(InpTp1R <= 0.0)
     {
      Print("INPUT ERROR: InpTp1R must be greater than zero.");
      errors++;
     }
   if(InpMaxStopAtr <= InpMinStopAtr)
     {
      PrintFormat("INPUT ERROR: InpMaxStopAtr (%.2f) must exceed InpMinStopAtr (%.2f).",
                  InpMaxStopAtr, InpMinStopAtr);
      errors++;
     }
   if(InpSlAtrMult <= 0.0)
     {
      Print("INPUT ERROR: InpSlAtrMult must be greater than zero.");
      errors++;
     }
   if(InpUsePartial && (InpPartialPct <= 0.0 || InpPartialPct >= 100.0))
     {
      PrintFormat("INPUT ERROR: InpPartialPct (%.1f) must be between 0 and 100 exclusive "
                  "- 100%% would leave no runner.", InpPartialPct);
      errors++;
     }
   if(InpUseTrailing && InpTrailStepPrice < 0.0)
     {
      Print("INPUT ERROR: InpTrailStepPrice cannot be negative.");
      errors++;
     }
   if(InpUseTrailing && InpTrailStartR < InpTp1R)
      PrintFormat("INPUT WARNING: InpTrailStartR (%.2f) is below InpTp1R (%.2f) - "
                  "the trail will engage before the partial is taken.",
                  InpTrailStartR, InpTp1R);

   //--- volatility band
   if(InpAtrBandMode == ATR_BAND_ABSOLUTE)
     {
      if(InpMaxAtrPrice > 0.0 && InpMinAtrPrice > 0.0 && InpMaxAtrPrice <= InpMinAtrPrice)
        {
         PrintFormat("INPUT ERROR: InpMaxAtrPrice (%.2f) must exceed InpMinAtrPrice (%.2f).",
                     InpMaxAtrPrice, InpMinAtrPrice);
         errors++;
        }
      Print("INPUT WARNING: the ABSOLUTE volatility band is fixed in dollars and will "
            "silently stop the EA when gold re-rates. RELATIVE mode is recommended.");
     }
   else
      if(InpAtrBandMode == ATR_BAND_RELATIVE)
        {
         if(InpAtrMaxRelative <= InpAtrMinRelative)
           {
            PrintFormat("INPUT ERROR: InpAtrMaxRelative (%.2f) must exceed InpAtrMinRelative (%.2f).",
                        InpAtrMaxRelative, InpAtrMinRelative);
            errors++;
           }
         if(InpAtrAvgPeriod < 20)
           {
            Print("INPUT ERROR: InpAtrAvgPeriod must be at least 20.");
            errors++;
           }
        }
      else
         if(InpAtrMaxPercent <= InpAtrMinPercent)
           {
            PrintFormat("INPUT ERROR: InpAtrMaxPercent (%.3f) must exceed InpAtrMinPercent (%.3f).",
                        InpAtrMaxPercent, InpAtrMinPercent);
            errors++;
           }

   //--- risk
   if(InpRiskMode != RISK_FIXED_LOT && InpRiskPercent <= 0.0)
     {
      Print("INPUT ERROR: InpRiskPercent must be greater than zero.");
      errors++;
     }
   if(InpRiskMode == RISK_FIXED_LOT && InpFixedLot <= 0.0)
     {
      Print("INPUT ERROR: InpFixedLot must be greater than zero in fixed-lot mode.");
      errors++;
     }
   if(InpMaxOpenPositions < 1)
     {
      Print("INPUT ERROR: InpMaxOpenPositions must be at least 1 or the EA can never trade.");
      errors++;
     }
   if(InpMaxMarginPct < 5.0 || InpMaxMarginPct > 95.0)
     {
      PrintFormat("INPUT ERROR: InpMaxMarginPct (%.1f) must be between 5 and 95.", InpMaxMarginPct);
      errors++;
     }

   //--- guard ladder must be ordered and inside the FTMO limits
   if(InpHardDailyLossPct <= InpSoftDailyLossPct)
     {
      PrintFormat("INPUT ERROR: InpHardDailyLossPct (%.2f) must exceed InpSoftDailyLossPct (%.2f).",
                  InpHardDailyLossPct, InpSoftDailyLossPct);
      errors++;
     }
   if(InpHardTotalLossPct <= InpSoftTotalLossPct)
     {
      PrintFormat("INPUT ERROR: InpHardTotalLossPct (%.2f) must exceed InpSoftTotalLossPct (%.2f).",
                  InpHardTotalLossPct, InpSoftTotalLossPct);
      errors++;
     }
   if(InpHardDailyLossPct >= InpFtmoDailyLossPct)
      PrintFormat("INPUT WARNING: InpHardDailyLossPct (%.2f) is not inside the FTMO daily limit "
                  "(%.2f) - it will be clamped.", InpHardDailyLossPct, InpFtmoDailyLossPct);
   if(InpHardTotalLossPct >= InpFtmoMaxLossPct)
      PrintFormat("INPUT WARNING: InpHardTotalLossPct (%.2f) is not inside the FTMO total limit "
                  "(%.2f) - it will be clamped.", InpHardTotalLossPct, InpFtmoMaxLossPct);

   //--- sessions
   if(!InpUseAsiaSession && !InpUseLondonSession && !InpUseNewYorkSession)
     {
      Print("INPUT ERROR: every trading session is disabled - the EA can never trade.");
      errors++;
     }
   if(InpUseAsiaSession    && (ParseHHMM(InpAsiaStart)    < 0 || ParseHHMM(InpAsiaEnd)    < 0))
     { Print("INPUT ERROR: Asia session times must be HH:MM.");     errors++; }
   if(InpUseLondonSession  && (ParseHHMM(InpLondonStart)  < 0 || ParseHHMM(InpLondonEnd)  < 0))
     { Print("INPUT ERROR: London session times must be HH:MM.");   errors++; }
   if(InpUseNewYorkSession && (ParseHHMM(InpNewYorkStart) < 0 || ParseHHMM(InpNewYorkEnd) < 0))
     { Print("INPUT ERROR: New York session times must be HH:MM."); errors++; }
   if(ParseHHMM(InpFridayCutoff) < 0 || ParseHHMM(InpWeekendFlatTime) < 0)
     { Print("INPUT ERROR: InpFridayCutoff / InpWeekendFlatTime must be HH:MM."); errors++; }
   if(InpUseDailyQuota && ParseHHMM(InpQuotaFromTime) < 0)
     { Print("INPUT ERROR: InpQuotaFromTime must be HH:MM."); errors++; }

   //--- quota must actually be a relaxation
   if(InpUseDailyQuota && InpQuotaScoreThreshold > InpScoreThreshold)
      PrintFormat("INPUT WARNING: InpQuotaScoreThreshold (%.1f) is stricter than the normal "
                  "threshold (%.1f) - quota mode will never fire.",
                  InpQuotaScoreThreshold, InpScoreThreshold);
   if(InpUseDailyQuota && (InpQuotaRiskFactor <= 0.0 || InpQuotaRiskFactor > 1.0))
     {
      PrintFormat("INPUT ERROR: InpQuotaRiskFactor (%.2f) must be in 0-1.", InpQuotaRiskFactor);
      errors++;
     }

   if(InpMaxSpreadPrice < 0.0)
     {
      Print("INPUT ERROR: InpMaxSpreadPrice cannot be negative (0 disables the filter).");
      errors++;
     }

   //--- news
   if(InpNewsSource != NEWS_SRC_OFF && InpNewsMinutesBefore + InpNewsMinutesAfter <= 0)
     {
      Print("INPUT ERROR: the news blackout window is zero minutes wide.");
      errors++;
     }

   //--- indicator periods
   if(InpEmaFastTrade >= InpEmaSlowTrade || InpEmaFastMid >= InpEmaSlowMid || InpEmaFastHigh >= InpEmaSlowHigh)
     {
      Print("INPUT ERROR: every fast EMA period must be shorter than its slow counterpart.");
      errors++;
     }
   if(InpMacdFast >= InpMacdSlow)
     {
      Print("INPUT ERROR: InpMacdFast must be shorter than InpMacdSlow.");
      errors++;
     }
   if(InpRsiPeriod < 2 || InpAdxPeriod < 2 || InpAtrPeriod < 2 || InpBandsPeriod < 2)
     {
      Print("INPUT ERROR: RSI / ADX / ATR / Bollinger periods must be at least 2.");
      errors++;
     }
   if(InpSwingLookback < 3 || InpTrailLookback < 3)
     {
      Print("INPUT ERROR: InpSwingLookback and InpTrailLookback must be at least 3.");
      errors++;
     }

   //--- RSI zones
   if(InpRsiBullLow >= InpRsiBullHigh || InpRsiBearLow >= InpRsiBearHigh)
     {
      Print("INPUT ERROR: each RSI zone's lower bound must be below its upper bound.");
      errors++;
     }

   if(errors > 0)
      PrintFormat("=== %d input error(s). The EA will NOT start. Fix them and reattach. ===", errors);

   return (errors == 0);
  }

//+------------------------------------------------------------------+
//| Counts distinct days on which this EA opened a trade, so the     |
//| FTMO minimum-trading-days counter survives a restart.            |
//+------------------------------------------------------------------+
int CountTradingDaysFromHistory(const datetime since)
  {
   if(!HistorySelect(since, TimeCurrent() + 86400))
      return 0;

   datetime seen[];
   int days = 0;
   int total = HistoryDealsTotal();

   for(int i = 0; i < total; i++)
     {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0)
         continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != g_symbol)
         continue;
      if((ulong)HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagic)
         continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_IN)
         continue;

      datetime t   = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
      datetime day = DayStart(t - (datetime)g_cetOffsetSec);   // CE(S)T day, as FTMO counts it

      bool known = false;
      for(int k = 0; k < days; k++)
        {
         if(seen[k] == day)
           {
            known = true;
            break;
           }
        }
      if(known)
         continue;

      ArrayResize(seen, days + 1);
      seen[days] = day;
      days++;
     }

   return days;
  }

//+------------------------------------------------------------------+
//| OnInit                                                           |
//+------------------------------------------------------------------+
int OnInit(void)
  {
   if(!ValidateInputs())
      return INIT_PARAMETERS_INCORRECT;

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

   //--- broker contract pre-flight: fails init rather than trading blind
   if(!DescribeAndValidateSymbol(g_symbol))
     {
      Print("FATAL: the broker's contract specification will not support this EA. See above.");
      return INIT_FAILED;
     }

   //--- sanity-check the spread limit against what this broker actually quotes
   double liveSpread = CurrentSpreadPrice();
   if(InpMaxSpreadPrice > 0.0 && liveSpread > 0.0 && liveSpread > InpMaxSpreadPrice * 3.0)
      PrintFormat("[Broker] WARNING: the live spread is %.2f but InpMaxSpreadPrice is %.2f. "
                  "If this persists the EA will never trade - check the quote and the setting.",
                  liveSpread, InpMaxSpreadPrice);

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

   g_conf.SetAtrBand(InpAtrBandMode,
                     InpAtrMinRelative, InpAtrMaxRelative,
                     InpAtrMinPercent, InpAtrMaxPercent,
                     InpAtrAvgPeriod);

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

   g_risk.SetMaxMarginPct(InpMaxMarginPct);

   //--- execution
   if(!g_exec.Init(g_symbol, InpTfTrade, InpMagic, InpSlippagePoints, InpVerboseLog))
      return INIT_FAILED;

   g_exec.SetManagement(InpTp1R, InpPartialPct, InpBreakevenLockR, InpTrailStartR,
                        InpTrailAtrMult, InpTrailStepPrice, InpTrailLookback,
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
   g_showParams  = InpShowParamsBlock;
   g_showMetrics = InpShowMetricsBlock;
   g_dash.Init(InpShowDashboard, InpDashX, InpDashY, InpDashWidth, InpDashFontSize);

   //--- rebuild the metrics so a restart mid-challenge does not zero the console
   if(InpRebuildStatsOnInit)
     {
      datetime since = TimeCurrent() - (datetime)(MathMax(1, InpStatsHistoryDays) * 86400);
      int rebuilt = g_stats.RebuildFromHistory(g_symbol, InpMagic, since);
      int histDays = CountTradingDaysFromHistory(since);
      if(histDays > 0)
        {
         g_risk.SetTradingDays(histDays);
         PrintFormat("[Stats] %d distinct trading day(s) recovered from history "
                     "(FTMO minimum is 4).", histDays);
        }

      if(rebuilt > 0)
         PrintFormat("[Stats] rebuilt %d closed trades from history: "
                     "win rate %.1f%%, PF %.2f, net %+.2f. "
                     "R metrics start fresh - the entry risk of historical trades is not recoverable.",
                     rebuilt, g_stats.WinRate(), g_stats.ProfitFactor(), g_stats.NetProfit());
     }

   EventSetTimer(20);

   UpdateDashboard();

   PrintFormat("=== XAUUSD FTMO Confluence EA initialised | BUILD %s ===", XFC_BUILD_ID);
   PrintFormat("=== diagnostics will be written to: %sFiles\\XFC_diagnostics.csv ===",
               TerminalInfoString(TERMINAL_COMMONDATA_PATH));

   // A start marker, written immediately. If this file does not appear the
   // moment the run begins, the binary in the terminal is not this build -
   // which is a faster answer than waiting for a run to finish.
   int mh = FileOpen("XFC_started.txt", FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(mh != INVALID_HANDLE)
     {
      FileWriteString(mh, StringFormat("build %s\r\nstarted %s\r\nsymbol %s %s\r\n"
                                       "leverage 1:%d\r\nATR band mode %d\r\ntester %s\r\n",
                                       XFC_BUILD_ID,
                                       TimeToString(TimeTradeServer(), TIME_DATE | TIME_MINUTES),
                                       g_symbol, EnumToString(InpTfTrade),
                                       (int)AccountInfoInteger(ACCOUNT_LEVERAGE),
                                       (int)InpAtrBandMode,
                                       (MQLInfoInteger(MQL_TESTER) ? "yes" : "no")));
      FileClose(mh);
     }
   else
      PrintFormat("WARNING: could not write the start marker (error %d)", GetLastError());

   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   LogVetoSummary(false);
   WriteDiagnosticFile();
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

   // Report periodically even when OnTick keeps returning early, so a long
   // quiet stretch produces evidence rather than nothing.
   datetime nowT = TimeTradeServer();
   if(g_lastSummary == 0 || (nowT - g_lastSummary) >= 6 * 3600)
     {
      LogVetoSummary(false);
      g_lastSummary = nowT;
     }

   g_news.Refresh(false);
   AccSweep();
   RefreshIdleStatus(TimeTradeServer());
   UpdateDashboard();
  }

//+------------------------------------------------------------------+
//| Veto accounting.                                                 |
//|                                                                  |
//| A backtest that traded on 13 days out of 379 gave no clue why.   |
//| Counting every rejection by cause turns that into a one-line     |
//| answer, on the console and in the journal.                       |
//+------------------------------------------------------------------+
void VetoRollDayIfNeeded(const datetime now)
  {
   datetime d = DayStart(now);
   if(d == g_vetoDayStamp)
      return;

   if(g_vetoDayStamp > 0 && g_barsSeenDay > 0)
      LogVetoSummary(true);

   g_vetoDayStamp  = d;
   g_barsSeenDay   = 0;
   g_ticksSeenDay  = 0;
   ArrayInitialize(g_vetoStatusDay, 0);
   ArrayInitialize(g_vetoGateDay, 0);
  }

//+------------------------------------------------------------------+
void CountVeto(const ENUM_EA_STATUS st)
  {
   int i = (int)st;
   if(i >= 0 && i < 9)
     {
      g_vetoStatus[i]++;
      g_vetoStatusDay[i]++;
     }
  }

//+------------------------------------------------------------------+
void CountGate(const ENUM_GATE_REASON g)
  {
   int i = (int)g;
   if(i >= 0 && i < GATE_REASON_COUNT)
     {
      g_vetoGate[i]++;
      g_vetoGateDay[i]++;
     }
  }

//+------------------------------------------------------------------+
//| Ranks the reasons and prints them. 'daily' selects today's counts.|
//+------------------------------------------------------------------+
void LogVetoSummary(const bool daily)
  {
   long bars  = (daily ? g_barsSeenDay  : g_barsSeen);
   long ticks = (daily ? g_ticksSeenDay : g_ticksSeen);

   // A silent period is exactly what needs explaining, so this prints even
   // when nothing happened. Zero ticks and zero bars mean very different
   // things: no ticks is missing history, ticks without bars is a filter.
   PrintFormat("[Why] %s: %d ticks, %d evaluated bars, %d trades.",
               (daily ? "today" : "since start"), (int)ticks, (int)bars,
               (daily ? (long)g_risk.TradesToday() : (long)g_stats.Trades()));

   if(ticks <= 0)
     {
      Print("        no ticks at all - the tester has no price data for this period, "
            "or the chart is not receiving quotes.");
      return;
     }
   if(bars <= 0)
     {
      Print("        ticks arrived but no bar was ever evaluated - every one was "
            "rejected before the signal check. The reasons below say which.");
     }

   for(int i = 0; i < 9; i++)
     {
      long c = (daily ? g_vetoStatusDay[i] : g_vetoStatus[i]);
      if(c > 0 && (ENUM_EA_STATUS)i != EA_STATUS_ACTIVE)
         PrintFormat("        %-22s %6d  (%.0f%% of ticks)", StatusLabel((ENUM_EA_STATUS)i),
                     (int)c, 100.0 * c / MathMax(1, ticks));
     }
   for(int g = 1; g < GATE_REASON_COUNT; g++)
     {
      long c = (daily ? g_vetoGateDay[g] : g_vetoGate[g]);
      if(c > 0)
         PrintFormat("        gate: %-16s %6d  (%.0f%% of bars)", GateLabel((ENUM_GATE_REASON)g),
                     (int)c, 100.0 * c / MathMax(1, bars));
     }
  }

//+------------------------------------------------------------------+
//| Writes the whole diagnosis to MQL5/Files/XFC_diagnostics.csv.    |
//|                                                                  |
//| The tester journal holds this too, but a file is far easier to   |
//| retrieve and to send on. Three backtests in a row were reported  |
//| from the equity curve alone, which cannot show WHY the EA was    |
//| idle - only that it was.                                         |
//+------------------------------------------------------------------+
void WriteDiagnosticFile(void)
  {
   if(!InpWriteDiagnosticFile)
      return;

   // Never during an optimisation. The filename comes from InpRunTag, which is
   // fixed across every pass, so all passes target one file and the parallel
   // agents overwrite each other - what survives is whichever agent finished
   // last, with nothing to say which pass it was. Analysing that file would be
   // worse than having none, so refuse and say why. The optimisation results
   // table is the correct source for per-pass metrics; re-run the winning
   // parameters as a single backtest to get a diagnosis of it.
   if(MQLInfoInteger(MQL_OPTIMIZATION))
     {
      static bool told = false;
      if(!told)
        {
         Print("[Why] optimisation pass - no diagnostics file written. Every pass "
               "shares InpRunTag and would overwrite the same file. Read the "
               "optimisation results tab, then re-run the winner as a single "
               "backtest for a diagnosis.");
         told = true;
        }
      return;
     }

   // FILE_COMMON matters. In the Strategy Tester a plain FileOpen writes into
   // the AGENT's private sandbox (Tester/Agent-.../MQL5/Files), not the
   // terminal's MQL5/Files - so the file appears to be missing. The common
   // folder is shared by the terminal and every agent, and is the one place
   // it can always be found.
   // One file per run. Comparison runs used to overwrite a single
   // XFC_diagnostics.csv, leaving nothing to compare but the equity curves -
   // which cannot show payoff ratio, and which mislead badly when a run
   // terminates early on a guard or on the profit target.
   string fname = (StringLen(InpRunTag) > 0
                   ? StringFormat("XFC_diag_%s.csv", InpRunTag)
                   : "XFC_diagnostics_UNTAGGED.csv");

   if(StringLen(InpRunTag) == 0)
      Print("[Why] InpRunTag is empty - writing XFC_diagnostics_UNTAGGED.csv. "
            "A generated .set file always sets it, so either the preset was not "
            "loaded or this binary predates the run-tag input.");

   int h = FileOpen(fname, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(h == INVALID_HANDLE)
     {
      PrintFormat("[Why] could not write the diagnostic file (error %d)", GetLastError());
      return;
     }

   FileWrite(h, "section", "item", "count", "pct", "note");
   FileWrite(h, "run", "build_id", XFC_BUILD_ID, "", "must match the build you compiled");
   FileWrite(h, "run", "run_tag", (StringLen(InpRunTag) > 0 ? InpRunTag : "untagged"), "", "");
   FileWrite(h, "run", "symbol", g_symbol, "", EnumToString(InpTfTrade));
   FileWrite(h, "run", "ticks_seen", (int)g_ticksSeen, "",
             (g_ticksSeen == 0 ? "NO PRICE DATA AT ALL for this period" : ""));
   FileWrite(h, "run", "bars_evaluated", (int)g_barsSeen, "",
             (g_ticksSeen > 0 && g_barsSeen == 0
              ? "ticks arrived but every bar was rejected before the signal check" : ""));
   FileWrite(h, "run", "trades_closed", (int)g_stats.Trades(), "", "");
   FileWrite(h, "run", "trading_days", (int)g_risk.TradingDays(), "", "FTMO minimum is 4");
   FileWrite(h, "run", "server_offset_h", (int)(g_gmtOffsetSec / 3600), "",
             (g_offsetPlausible ? "auto-detected" : "DETECTION FAILED - set it manually"));
   FileWrite(h, "run", "account_leverage", (int)AccountInfoInteger(ACCOUNT_LEVERAGE), "",
             "1:30 = FTMO Swing, 1:100 = normal");
   FileWrite(h, "run", "atr_band_mode", (int)InpAtrBandMode, "",
             "0 relative, 1 percent, 2 absolute");
   FileWrite(h, "run", "news_events_loaded", (int)g_news.EventCount(), "", g_news.LastError());

   for(int i = 0; i < 9; i++)
      if(g_vetoStatus[i] > 0)
         FileWrite(h, "status", StatusLabel((ENUM_EA_STATUS)i), (int)g_vetoStatus[i],
                   DoubleToString(100.0 * g_vetoStatus[i] / MathMax(1, g_ticksSeen), 1), "% of ticks");

   for(int g = 1; g < GATE_REASON_COUNT; g++)
      if(g_vetoGate[g] > 0)
         FileWrite(h, "gate", GateLabel((ENUM_GATE_REASON)g), (int)g_vetoGate[g],
                   DoubleToString(100.0 * g_vetoGate[g] / MathMax(1, g_barsSeen), 1), "% of bars");

   // How a run ENDED decides whether its numbers are comparable at all.
   string ending = "ran to the end of the period";
   if(g_risk.TargetReached())
      ending = "STOPPED EARLY - profit target reached, stood down by design";
   else
      if(g_risk.TotalDrawdownPct() >= InpSoftTotalLossPct)
         ending = "STOPPED EARLY - total loss guard tripped";
   FileWrite(h, "run", "ended", ending, "", "early stops are NOT comparable with full runs");
   FileWrite(h, "run", "final_profit_pct", DoubleToString(g_risk.ProfitPct(), 2), "", "");
   FileWrite(h, "run", "max_total_dd_pct", DoubleToString(g_risk.MaxTotalDrawdownPct(), 2), "",
             "true peak-to-trough; acceptance threshold is 5%");
   FileWrite(h, "run", "final_total_dd_pct", DoubleToString(g_risk.TotalDrawdownPct(), 2), "",
             "drawdown at the moment the run ended");

   FileWrite(h, "metrics", "win_rate_pct", DoubleToString(g_stats.WinRate(), 1), "", "");
   FileWrite(h, "metrics", "profit_factor", DoubleToString(g_stats.ProfitFactor(), 2), "", "");
   FileWrite(h, "metrics", "payoff_ratio", DoubleToString(g_stats.PayoffRatio(), 2), "",
             "needs ~1.6 at a 45% win rate");
   FileWrite(h, "metrics", "expectancy_R", DoubleToString(g_stats.ExpectancyR(), 2), "",
             StringFormat("n=%d", g_stats.RSample()));

   FileClose(h);
   PrintFormat("[Why] diagnosis written to: %sFiles\\XFC_diagnostics.csv",
               TerminalInfoString(TERMINAL_COMMONDATA_PATH));
  }

//+------------------------------------------------------------------+
//| The single dominant reason, for the console.                     |
//+------------------------------------------------------------------+
string TopVetoReason(void)
  {
   long best = 0;
   string label = "none";

   for(int i = 0; i < 9; i++)
     {
      if((ENUM_EA_STATUS)i == EA_STATUS_ACTIVE) continue;
      if(g_vetoStatus[i] > best) { best = g_vetoStatus[i]; label = StatusLabel((ENUM_EA_STATUS)i); }
     }
   for(int g = 1; g < GATE_REASON_COUNT; g++)
      if(g_vetoGate[g] > best) { best = g_vetoGate[g]; label = GateLabel((ENUM_GATE_REASON)g); }

   if(g_ticksSeen > 0 && g_barsSeen <= 0)
      return "no bar ever reached the signal check";
   if(best <= 0 || g_ticksSeen <= 0)
      return "nothing blocking";
   return StringFormat("%s (%.0f%% of ticks)", label, 100.0 * best / MathMax(1, g_ticksSeen));
  }

//+------------------------------------------------------------------+
//| Records what the EA is doing, for the console banner. Called at  |
//| every decision point in OnTick so the panel and the trade logic  |
//| can never disagree about why nothing is happening.               |
//+------------------------------------------------------------------+
void SetStatus(const ENUM_EA_STATUS st, const string detail)
  {
   if(st != g_status || st != EA_STATUS_ACTIVE)
      CountVeto(st);
   g_status          = st;
   g_statusDetail    = detail;
   g_lastBlockReason = detail;
  }

//+------------------------------------------------------------------+
//| OnTick                                                           |
//+------------------------------------------------------------------+
void OnTick(void)
  {
   datetime now = TimeTradeServer();

   // Counted FIRST. Previously the day rollover sat below eight possible
   // early returns, so on a day the EA never traded the summary never
   // printed - the diagnostic was silent in exactly the case it existed
   // to explain.
   VetoRollDayIfNeeded(now);
   g_ticksSeen++;
   g_ticksSeenDay++;

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
      SetStatus(EA_STATUS_HALTED, g_risk.LastReason());
      return;
     }
   g_hardStopped = false;

   //--- 3. weekend flat
   if(ShouldFlattenForWeekend(now))
     {
      if(g_exec.HasOpenPosition())
         g_exec.CloseAll("weekend flat");
      SetStatus(EA_STATUS_CLOSED_WEEKEND, "flat for the weekend");
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
         SetStatus(EA_STATUS_PAUSED_NEWS, "flattened ahead of a release");
         return;
        }
     }

   if(blackout)
     {
      SetStatus(EA_STATUS_PAUSED_NEWS, g_news.BlackoutTitle());
      return;
     }

   if(action == GUARD_SOFT_HALT)
     {
      if(g_risk.TargetReached())
         SetStatus(EA_STATUS_TARGET_REACHED, g_risk.LastReason());
      else
         if(g_risk.TradesToday() >= InpMaxTradesPerDay && InpMaxTradesPerDay > 0)
            SetStatus(EA_STATUS_PAUSED_LIMIT, g_risk.LastReason());
         else
            SetStatus(EA_STATUS_PAUSED_RISK, g_risk.LastReason());
      return;
     }

   //--- 5. session
   string why = "";
   if(!InTradingSession(now, why))
     {
      SetStatus(EA_STATUS_PAUSED_SESSION, why);
      return;
     }

   //--- 6. one position at a time
   if(g_exec.OpenPositions() >= InpMaxOpenPositions)
     {
      SetStatus(EA_STATUS_IN_TRADE, "managing an open position");
      return;
     }

   //--- 7. spacing between entries
   if(InpMinMinutesBetween > 0 && g_lastEntryTime > 0)
     {
      if((now - g_lastEntryTime) < InpMinMinutesBetween * 60)
        {
         int waitMin = InpMinMinutesBetween - (int)((now - g_lastEntryTime) / 60);
         SetStatus(EA_STATUS_PAUSED_LIMIT, StringFormat("entry spacing, %dm left", waitMin));
         return;
        }
     }

   //--- 8. spread
   double spread = CurrentSpreadPrice();
   if(InpMaxSpreadPrice > 0.0 && spread > InpMaxSpreadPrice)
     {
      SetStatus(EA_STATUS_PAUSED_LIMIT,
                StringFormat("spread %.2f > %.2f limit", spread, InpMaxSpreadPrice));
      return;
     }

   //--- 9. one evaluation per closed bar
   datetime barTime = iTime(g_symbol, InpTfTrade, 0);
   if(barTime <= 0)
     {
      // no series data for this bar - do not latch it, or a single gap would
      // block every future evaluation
      SetStatus(EA_STATUS_ACTIVE, "no bar data for the execution timeframe");
      return;
     }
   if(barTime == g_lastBarTime)
      return;
   g_lastBarTime = barTime;

   g_barsSeen++;
   g_barsSeenDay++;

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

   CountGate(g_conf.GateCode());

   if(dir == SIGNAL_NONE)
     {
      SetStatus(EA_STATUS_ACTIVE, snap.reason);
      if(InpVerboseLog)
         PrintFormat("[Signal] %s", snap.reason);
      return;
     }

   //--- 12. build the stop and targets
   if(!g_conf.BuildLevels(dir, snap.atr, InpSlAtrMult, InpSwingLookback,
                          InpSwingBufferAtr, InpMinStopAtr, InpMaxStopAtr,
                          InpTp1R, InpTp2R, snap))
     {
      SetStatus(EA_STATUS_ACTIVE, "stop construction failed");
      return;
     }

   //--- 13. size it
   string sizeReason = "";
   double lots = g_risk.LotsForRisk(InpRiskPercent * riskMult, snap.riskDistance,
                                    InpRiskMode, InpFixedLot, sizeReason);
   if(lots <= 0.0)
     {
      // A valid signal that cannot be sized is the most dangerous kind of
      // silent skip, so it is always logged with the specific cause.
      SetStatus(EA_STATUS_PAUSED_RISK, sizeReason);
      PrintFormat("[Trade] SIGNAL SKIPPED (%s %s at %.2f): %s",
                  (dir == SIGNAL_BUY ? "BUY" : "SELL"), g_symbol, snap.entry, sizeReason);
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

      // remember what this trade stands to lose, so the console can report
      // its outcome as an R multiple once it closes
      AccSetRisk(ticket, MoneyForDistance(g_symbol, snap.riskDistance, lots));
      SetStatus(EA_STATUS_IN_TRADE, StringFormat("%s opened in %s",
                (dir == SIGNAL_BUY ? "long" : "short"),
                (StringLen(g_activeSession) > 0 ? g_activeSession : "session")));

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
         double total    = g_accProfit[idx];
         double riskUsed = g_accRisk[idx];

         g_risk.RegisterClosedTrade(total);
         g_stats.Register(total, riskUsed);

         string rText = (riskUsed > 0.0 ? StringFormat("%+.2fR", total / riskUsed) : "R n/a");
         PrintFormat("[Result] position #%I64u closed %+.2f (%s) | today W/L %d/%d | "
                     "streak %d | win rate %.0f%% PF %.2f exp %+.2fR",
                     posId, total, rText, g_risk.WinsToday(), g_risk.LossesToday(),
                     g_risk.ConsecutiveLosses(), g_stats.WinRate(),
                     g_stats.ProfitFactor(), g_stats.ExpectancyR());
         AccRemove(idx);
        }
     }
  }

//+------------------------------------------------------------------+
//| AURUM CONSOLE                                                    |
//+------------------------------------------------------------------+
color StatusColor(const ENUM_EA_STATUS st)
  {
   switch(st)
     {
      case EA_STATUS_ACTIVE:         return AURUM_GOLD_BRIGHT;
      case EA_STATUS_IN_TRADE:       return AURUM_GOOD;
      case EA_STATUS_TARGET_REACHED: return AURUM_GOOD;
      case EA_STATUS_PAUSED_NEWS:    return AURUM_BAD;
      case EA_STATUS_HALTED:         return AURUM_BAD;
      case EA_STATUS_PAUSED_RISK:    return AURUM_WARN;
      case EA_STATUS_PAUSED_LIMIT:   return AURUM_WARN;
      default:                       return AURUM_LABEL;
     }
  }

//+------------------------------------------------------------------+
//| Keeps the banner honest when no ticks are arriving - over a      |
//| weekend or a long news blackout OnTick never runs, so the timer  |
//| refreshes the states that change on the clock alone.             |
//+------------------------------------------------------------------+
void RefreshIdleStatus(const datetime now)
  {
   if(g_status == EA_STATUS_HALTED || g_status == EA_STATUS_TARGET_REACHED)
      return;

   if(g_exec.HasOpenPosition())
      return;                                  // OnTick owns the in-trade state

   if(ShouldFlattenForWeekend(now))
     {
      SetStatus(EA_STATUS_CLOSED_WEEKEND, "flat for the weekend");
      return;
     }

   if(g_news.IsBlackout(now))
     {
      SetStatus(EA_STATUS_PAUSED_NEWS, g_news.BlackoutTitle());
      return;
     }

   string why = "";
   if(!InTradingSession(now, why))
      SetStatus(EA_STATUS_PAUSED_SESSION, why);
  }

//+------------------------------------------------------------------+
string SessionSummary(void)
  {
   string parts = "";
   if(InpUseAsiaSession)    parts += "Asia ";
   if(InpUseLondonSession)  parts += "London ";
   if(InpUseNewYorkSession) parts += "NY";
   StringTrimRight(parts);
   return (StringLen(parts) > 0 ? parts : "NONE ENABLED");
  }

//+------------------------------------------------------------------+
//| The strategy parameter block - what is actually loaded, so a     |
//| wrong preset is visible without opening the Inputs tab.          |
//+------------------------------------------------------------------+
void DrawParameters(void)
  {
   g_dash.Section("STRATEGY PARAMETERS");

   g_dash.Row("Timeframes",
              StringFormat("%s / %s / %s",
                           StringSubstr(EnumToString(InpTfTrade), 7),
                           StringSubstr(EnumToString(InpTfMid), 7),
                           StringSubstr(EnumToString(InpTfHigh), 7)));

   g_dash.Row("Confluence gate",
              StringFormat("score %.0f, margin %.0f", InpScoreThreshold, InpDominanceMargin));

   g_dash.Row("Hard gates",
              StringFormat("ADX>%.0f  ATR %.1f-%.1f  ext<%.1f",
                           InpAdxMin, InpMinAtrPrice, InpMaxAtrPrice, InpMaxExtensionAtr));

   g_dash.Row("Risk / trade",
              StringFormat("%.2f%% %s", InpRiskPercent,
                           (InpRiskMode == RISK_PERCENT_INITIAL ? "of initial" :
                            InpRiskMode == RISK_PERCENT_BALANCE ? "of balance" :
                            InpRiskMode == RISK_PERCENT_EQUITY  ? "of equity"  : "fixed lot")));

   g_dash.Row("Stop",
              StringFormat("%.2f x ATR, %.1f-%.1f ATR clamp",
                           InpSlAtrMult, InpMinStopAtr, InpMaxStopAtr));

   g_dash.Row("Targets",
              StringFormat("TP1 %.1fR (%.0f%%)  TP2 %.1fR",
                           InpTp1R, (InpUsePartial ? InpPartialPct : 0.0), InpTp2R));

   g_dash.Row("Trail",
              (InpUseTrailing ? StringFormat("from %.1fR, %.1f x ATR, step %.2f",
                                            InpTrailStartR, InpTrailAtrMult, InpTrailStepPrice)
                              : "off"));

   g_dash.Row("Guards daily",
              StringFormat("soft %.1f%% / hard %.1f%% (FTMO %.0f%%)",
                           InpSoftDailyLossPct, InpHardDailyLossPct, InpFtmoDailyLossPct),
              AURUM_TEXT);

   g_dash.Row("Guards total",
              StringFormat("soft %.1f%% / hard %.1f%% (FTMO %.0f%%)",
                           InpSoftTotalLossPct, InpHardTotalLossPct, InpFtmoMaxLossPct),
              AURUM_TEXT);

   g_dash.Row("Limits",
              StringFormat("%d/day, %d open, %dm apart, %d loss streak",
                           InpMaxTradesPerDay, InpMaxOpenPositions,
                           InpMinMinutesBetween, InpMaxConsecLosses));

   g_dash.Row("Sessions", SessionSummary(),
              (StringLen(SessionSummary()) > 0 && SessionSummary() != "NONE ENABLED"
               ? AURUM_TEXT : AURUM_BAD));

   g_dash.Row("Daily quota",
              (InpUseDailyQuota ? StringFormat("from %s GMT, score %.0f, %.0f%% size",
                                               InpQuotaFromTime, InpQuotaScoreThreshold,
                                               InpQuotaRiskFactor * 100.0)
                                : "off"));

   string newsCfg;
   switch(InpNewsSource)
     {
      case NEWS_SRC_OFF:           newsCfg = "OFF";                    break;
      case NEWS_SRC_MT5:           newsCfg = "MT5 calendar";           break;
      case NEWS_SRC_FOREXFACTORY:  newsCfg = "ForexFactory";           break;
      default:                     newsCfg = "ForexFactory + MT5";     break;
     }
   g_dash.Row("News filter",
              StringFormat("%s, -%d/+%dm", newsCfg, InpNewsMinutesBefore, InpNewsMinutesAfter),
              (InpNewsSource == NEWS_SRC_OFF ? AURUM_BAD : AURUM_TEXT));
  }

//+------------------------------------------------------------------+
//| Performance metrics for this strategy on this account.           |
//+------------------------------------------------------------------+
void DrawMetrics(void)
  {
   g_dash.Section("METRICS");

   if(g_stats.Trades() == 0)
     {
      g_dash.Row("Closed trades", "none yet", AURUM_LABEL);
      return;
     }

   double wr = g_stats.WinRate();
   color wrColor = (wr >= 60.0 ? AURUM_GOOD : (wr >= 45.0 ? AURUM_WARN : AURUM_BAD));

   double pf = g_stats.ProfitFactor();
   color pfColor = (pf >= 1.35 ? AURUM_GOOD : (pf >= 1.0 ? AURUM_WARN : AURUM_BAD));

   double payoff = g_stats.PayoffRatio();
   color payColor = (payoff >= 1.3 ? AURUM_GOOD : (payoff >= 1.0 ? AURUM_WARN : AURUM_BAD));

   g_dash.Row("Closed trades",
              StringFormat("%d  (%dW / %dL / %dBE)",
                           g_stats.Trades(), g_stats.Wins(), g_stats.Losses(), g_stats.Breakeven()));

   g_dash.Row("Win rate", StringFormat("%.1f%%", wr), wrColor);
   g_dash.Row("Profit factor", StringFormat("%.2f", pf), pfColor);
   g_dash.Row("Avg win / loss",
              StringFormat("%.2f / %.2f  = %.2f", g_stats.AvgWin(), g_stats.AvgLoss(), payoff),
              payColor);

   if(g_stats.RSample() > 0)
     {
      double expR = g_stats.ExpectancyR();
      g_dash.Row("Expectancy",
                 StringFormat("%+.2fR per trade  (n=%d)", expR, g_stats.RSample()),
                 (expR > 0.0 ? AURUM_GOOD : AURUM_BAD));
      g_dash.Row("Avg R win / loss",
                 StringFormat("%+.2fR / -%.2fR", g_stats.AvgWinR(), g_stats.AvgLossR()));
      g_dash.Row("Total R", StringFormat("%+.2fR", g_stats.TotalR()),
                 (g_stats.TotalR() > 0.0 ? AURUM_GOOD : AURUM_BAD));
     }
   else
      g_dash.Row("Expectancy",
                 StringFormat("%+.2f per trade", g_stats.Expectancy()),
                 (g_stats.Expectancy() > 0.0 ? AURUM_GOOD : AURUM_BAD));

   g_dash.Row("Best / worst",
              StringFormat("%+.2f / -%.2f", g_stats.LargestWin(), g_stats.LargestLoss()));

   g_dash.Row("Streaks",
              StringFormat("now %d,  max %dW / %dL",
                           g_stats.CurrentStreak(), g_stats.MaxWinStreak(), g_stats.MaxLossStreak()),
              (g_stats.CurrentStreak() < 0 ? AURUM_WARN : AURUM_TEXT));

   g_dash.Row("Closed-equity DD",
              StringFormat("%.2f", g_stats.MaxDrawdown()),
              (g_stats.MaxDrawdown() > 0.0 ? AURUM_WARN : AURUM_TEXT));
  }

//+------------------------------------------------------------------+
void UpdateDashboard(void)
  {
   if(!InpShowDashboard)
      return;

   datetime now = TimeTradeServer();

   double dailyDd = g_risk.DailyDrawdownPct();
   double totalDd = g_risk.TotalDrawdownPct();
   double profit  = g_risk.ProfitPct();

   color ddColor = AURUM_GOOD;
   if(dailyDd > InpSoftDailyLossPct * 0.5) ddColor = AURUM_WARN;
   if(dailyDd >= InpSoftDailyLossPct)      ddColor = AURUM_BAD;

   color tdColor = AURUM_GOOD;
   if(totalDd > InpSoftTotalLossPct * 0.5) tdColor = AURUM_WARN;
   if(totalDd >= InpSoftTotalLossPct)      tdColor = AURUM_BAD;

   g_dash.Begin();

   //================= header ======================================
   g_dash.Header("AURUM  |  XAUUSD FTMO CONFLUENCE",
                 StringFormat("%s  %s   server %s   %s",
                              g_symbol,
                              StringSubstr(EnumToString(InpTfTrade), 7),
                              TimeToString(now, TIME_MINUTES),
                              TZ_OffsetText(g_gmtOffsetSec)));

   //================= status banner ===============================
   g_dash.Banner("> " + StatusLabel(g_status), StatusColor(g_status));
   g_dash.Row("", (StringLen(g_statusDetail) > 0 ? g_statusDetail : "-"), AURUM_LABEL);

   //================= challenge progress ==========================
   g_dash.Section("FTMO PROGRESS");

   g_dash.Row("Target",
              StringFormat("%+.2f%%  of  %.2f%%", profit, InpProfitTargetPct),
              (profit >= 0.0 ? AURUM_GOOD : AURUM_BAD));
   g_dash.Row("Daily drawdown",
              StringFormat("%.2f%%   soft %.1f / hard %.1f", dailyDd,
                           InpSoftDailyLossPct, InpHardDailyLossPct), ddColor);
   g_dash.Row("Total drawdown",
              StringFormat("%.2f%%   soft %.1f / hard %.1f", totalDd,
                           InpSoftTotalLossPct, InpHardTotalLossPct), tdColor);
   g_dash.Row("Trading days",
              StringFormat("%d   (FTMO minimum 4)", g_risk.TradingDays()),
              (g_risk.TradingDays() >= 4 ? AURUM_GOOD : AURUM_WARN));
   g_dash.Row("Today",
              StringFormat("%d trades, %dW/%dL, realised %+.2f",
                           g_risk.TradesToday(), g_risk.WinsToday(),
                           g_risk.LossesToday(), g_risk.RealisedToday()));
   g_dash.Row("Risk next trade",
              StringFormat("%.2f%%  x%.2f streak factor",
                           InpRiskPercent, g_risk.RiskFactor()),
              (g_risk.RiskFactor() < 1.0 ? AURUM_WARN : AURUM_TEXT));
   g_dash.Row("Day anchor",
              StringFormat("%.2f  from %s",
                           g_risk.DayStartBalance(),
                           TimeToString(g_risk.CurrentDayStart(), TIME_DATE | TIME_MINUTES)));
   g_dash.Row("Budget left today",
              StringFormat("%.2f before the soft guard", g_risk.RemainingDailyRiskMoney()),
              (g_risk.RemainingDailyRiskMoney() <= 0.0 ? AURUM_BAD : AURUM_TEXT));

   //================= market ======================================
   g_dash.Section("MARKET");

   g_dash.Row("Session", SessionStatusText(now),
              (StringLen(CurrentSessionName(now)) > 0 ? AURUM_GOOD : AURUM_LABEL));
   g_dash.Row("Clock",
              StringFormat("CET %+.0fh   EU %s / US %s",
                           g_cetOffsetSec / 3600.0,
                           (TZ_IsEuSummerTime(UtcNow()) ? "DST" : "std"),
                           (TZ_IsUsSummerTime(UtcNow()) ? "DST" : "std")),
              (g_offsetPlausible ? AURUM_TEXT : AURUM_BAD));

   double spread = CurrentSpreadPrice();
   g_dash.Row("Spread",
              StringFormat("%.2f  (%.0f pts, limit %.2f)", spread, CurrentSpreadPoints(), InpMaxSpreadPrice),
              (InpMaxSpreadPrice > 0.0 && spread > InpMaxSpreadPrice ? AURUM_BAD : AURUM_TEXT));
   g_dash.Row("Indicators",
              StringFormat("ATR %.2f  ADX %.1f  RSI %.1f", g_conf.Atr(), g_conf.Adx(), g_conf.Rsi()));
   g_dash.Row("VWAP", StringFormat("%.2f", g_conf.Vwap()));

   //================= news ========================================
   g_dash.Section("NEWS");

   if(InpNewsSource == NEWS_SRC_OFF)
      g_dash.Row("Filter", "OFF - not FTMO compliant", AURUM_BAD);
   else
      if(g_status == EA_STATUS_PAUSED_NEWS)
        {
         g_dash.Row("BLACKOUT", g_news.BlackoutTitle(), AURUM_BAD);
         g_dash.Row("Clears at",
                    TimeToString(g_news.BlackoutEnds(), TIME_MINUTES), AURUM_BAD);
        }
      else
        {
         g_dash.Row("Events loaded",
                    StringFormat("%d", g_news.EventCount()),
                    (g_news.EventCount() > 0 ? AURUM_TEXT : AURUM_WARN));
         g_dash.Row("Next", g_news.NextEventText(now));
         if(StringLen(g_news.LastError()) > 0)
            g_dash.Row("Feed warning", g_news.LastError(), AURUM_WARN);
        }

   //================= why not trading =============================
   g_dash.Section("WHY NOT TRADING");
   g_dash.Row("Ticks / bars",
              StringFormat("%d ticks, %d bars evaluated", (int)g_ticksSeen, (int)g_barsSeen),
              (g_ticksSeen > 0 && g_barsSeen == 0 ? AURUM_BAD : AURUM_TEXT));
   g_dash.Row("Dominant blocker", TopVetoReason(),
              (g_barsSeen > 200 && g_stats.Trades() == 0 ? AURUM_BAD : AURUM_TEXT));
   g_dash.Row("ATR band",
              StringFormat("%s, now %.3f",
                           (InpAtrBandMode == ATR_BAND_RELATIVE ? "relative" :
                            InpAtrBandMode == ATR_BAND_PERCENT  ? "percent"  : "absolute"),
                           g_conf.AtrRatio()));

   //================= positions ===================================
   g_dash.Section("POSITIONS");
   g_dash.Row("Open",
              StringFormat("%d   %s", g_exec.OpenPositions(), g_exec.StateText()),
              (g_exec.OpenPositions() > 0 ? AURUM_GOOD : AURUM_LABEL));
   if(g_exec.OpenPositions() > 0)
      g_dash.Row("At risk now",
                 StringFormat("%.2f to the stops", g_exec.OpenRiskMoney()), AURUM_WARN);

   //================= optional blocks =============================
   if(g_showMetrics)
      DrawMetrics();
   if(g_showParams)
      DrawParameters();

   g_dash.BuildButtons(g_showParams, g_showMetrics);
   g_dash.End();
  }

//+------------------------------------------------------------------+
//| Console button clicks                                            |
//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
  {
   if(id != CHARTEVENT_OBJECT_CLICK)
      return;

   if(g_dash.IsParamsButton(sparam))
     {
      g_showParams = !g_showParams;
      UpdateDashboard();
     }
   else
      if(g_dash.IsMetricsButton(sparam))
        {
         g_showMetrics = !g_showMetrics;
         UpdateDashboard();
        }
  }
//+------------------------------------------------------------------+
