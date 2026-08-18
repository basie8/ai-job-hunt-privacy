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
input int             InpCetOffsetHours      = 0;     // Server time minus CE(S)T, in hours

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

input group "=== Sessions ==="
input bool            InpSessionTimesAreGmt  = true;      // Session times below are GMT
input int             InpGmtOffsetHours      = 0;         // Manual server-GMT offset (hours)
input bool            InpUseManualGmtOffset  = false;     // Use the manual offset instead of auto-detect
input bool            InpUseSession1         = true;      // Trade the London session
input string          InpSession1Start       = "07:00";   // London start
input string          InpSession1End         = "11:00";   // London end
input bool            InpUseSession2         = true;      // Trade the London/NY overlap
input string          InpSession2Start       = "12:30";   // Overlap start
input string          InpSession2End         = "17:00";   // Overlap end
input bool            InpTradeMonday         = true;      // Trade Monday
input bool            InpTradeFriday         = true;      // Trade Friday
input string          InpFridayCutoff        = "15:00";   // Friday: no new trades after
input bool            InpFlatBeforeWeekend   = true;      // Close everything before the weekend
input string          InpWeekendFlatTime     = "19:00";   // Friday flatten time
input int             InpMaxSpreadPoints     = 45;        // Max spread to trade (points)
input int             InpMinMinutesBetween   = 45;        // Minimum minutes between entries

input group "=== Daily quota (the 'at least one trade a day' rule) ==="
input bool            InpUseDailyQuota       = true;      // Relax the threshold late in the day
input string          InpQuotaFromTime       = "14:30";   // Quota mode starts at
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
int      g_gmtOffsetSec = 0;
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
int ToServerMinutes(const string hhmm)
  {
   int m = ParseHHMM(hhmm);
   if(m < 0)
      return -1;
   if(InpSessionTimesAreGmt)
     {
      m += g_gmtOffsetSec / 60;
      m = ((m % 1440) + 1440) % 1440;
     }
   return m;
  }

//+------------------------------------------------------------------+
bool InTradingSession(const datetime serverNow, string &why)
  {
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

   int nowMin = MinutesOfDay(serverNow);

   if(st.day_of_week == 5)
     {
      int cutoff = ToServerMinutes(InpFridayCutoff);
      if(cutoff >= 0 && nowMin >= cutoff)
        {
         why = "past the Friday cutoff";
         return false;
        }
     }

   bool inWindow = false;
   if(InpUseSession1)
     {
      int a = ToServerMinutes(InpSession1Start);
      int b = ToServerMinutes(InpSession1End);
      if(a >= 0 && b >= 0 && InMinuteWindow(nowMin, a, b))
         inWindow = true;
     }
   if(!inWindow && InpUseSession2)
     {
      int a = ToServerMinutes(InpSession2Start);
      int b = ToServerMinutes(InpSession2End);
      if(a >= 0 && b >= 0 && InMinuteWindow(nowMin, a, b))
         inWindow = true;
     }

   if(!inWindow)
     {
      why = "outside the trading sessions";
      return false;
     }

   why = "";
   return true;
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
   int flat = ToServerMinutes(InpWeekendFlatTime);
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

   g_gmtOffsetSec = ServerGmtOffsetSeconds(InpGmtOffsetHours, InpUseManualGmtOffset);
   PrintFormat("[Init] server-GMT offset resolved to %+d hours.", g_gmtOffsetSec / 3600);

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

   //--- risk guard
   if(!g_risk.Init(g_symbol, InpMagic, InpInitialCapital,
                   InpFtmoDailyLossPct, InpFtmoMaxLossPct,
                   InpSoftDailyLossPct, InpHardDailyLossPct,
                   InpSoftTotalLossPct, InpHardTotalLossPct,
                   InpProfitTargetPct, InpStopAtTarget,
                   InpMaxTradesPerDay, InpMaxConsecLosses,
                   InpLossStreakFactor, InpCetOffsetHours * 3600))
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
      int quotaFrom = ToServerMinutes(InpQuotaFromTime);
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
