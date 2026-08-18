//+------------------------------------------------------------------+
//|                                                    RiskGuard.mqh |
//|  FTMO 2-STEP compliance layer.                                   |
//|                                                                  |
//|  FTMO objectives this class enforces (2-step programme):         |
//|    * Max Daily Loss   5% of INITIAL capital, measured against    |
//|                       the balance recorded at 00:00 CE(S)T and   |
//|                       INCLUDING open floating P/L.               |
//|    * Max Total Loss  10% of INITIAL capital, a fixed floor that  |
//|                       never trails up.                           |
//|    * Profit target   10% (Challenge) / 5% (Verification).        |
//|    * Min trading days 4 per phase.                               |
//|                                                                  |
//|  The class deliberately trips WELL BEFORE the real limits so a   |
//|  single bad sequence or a weekend gap cannot breach the account. |
//+------------------------------------------------------------------+
#ifndef __XAUUSD_FTMO_RISKGUARD_MQH__
#define __XAUUSD_FTMO_RISKGUARD_MQH__

//--- version stamp. The EA checks for this, so copying a new .mq5
//--- next to a stale .mqh fails with one named error instead of forty.
#define XFC_V_RISKGUARD_2

#include "CoreDefs.mqh"

//+------------------------------------------------------------------+
class CRiskGuard
  {
private:
   double            m_initialCapital;
   double            m_dayStartBalance;
   double            m_dayStartEquity;
   datetime          m_currentDayStart;     // CE(S)T midnight expressed in server time
   int               m_cetOffsetSec;        // server time - CE(S)T, in seconds

   //--- configured limits, all as a fraction of the INITIAL capital
   double            m_ftmoDailyLossPct;    // the real rule (5%)
   double            m_ftmoMaxLossPct;      // the real rule (10%)
   double            m_softDailyLossPct;    // stop opening trades here
   double            m_hardDailyLossPct;    // flatten everything here
   double            m_softTotalLossPct;    // stop opening trades here
   double            m_hardTotalLossPct;    // flatten everything here
   double            m_profitTargetPct;     // phase target
   bool              m_stopAtTarget;

   //--- session / streak controls
   int               m_maxTradesPerDay;
   int               m_maxConsecutiveLosses;
   double            m_lossStreakRiskFactor;

   //--- runtime state
   int               m_tradesToday;
   int               m_winsToday;
   int               m_lossesToday;
   int               m_consecutiveLosses;
   double            m_realisedToday;
   int               m_tradingDays;
   bool              m_targetReached;
   bool              m_dayLockedOut;
   string            m_lastReason;
   ulong             m_magic;
   string            m_symbol;

   double            PctOfInitial(const double pct) const { return m_initialCapital * pct / 100.0; }
   void              RollDay(const datetime serverNow);

public:
                     CRiskGuard(void);

   bool              Init(const string symbol,
                          const ulong magic,
                          const double initialCapital,
                          const double ftmoDailyLossPct,
                          const double ftmoMaxLossPct,
                          const double softDailyLossPct,
                          const double hardDailyLossPct,
                          const double softTotalLossPct,
                          const double hardTotalLossPct,
                          const double profitTargetPct,
                          const bool   stopAtTarget,
                          const int    maxTradesPerDay,
                          const int    maxConsecutiveLosses,
                          const double lossStreakRiskFactor,
                          const int    cetOffsetSec);

   //--- call once per tick; handles the CE(S)T day rollover
   void              OnTick(const datetime serverNow);

   //--- overall verdict for this moment
   ENUM_GUARD_ACTION Evaluate(void);

   //--- position sizing
   double            LotsForRisk(const double riskPercent,
                                 const double stopDistancePrice,
                                 const ENUM_RISK_MODE mode,
                                 const double fixedLot,
                                 string &reason);

   //--- how much money a single trade is allowed to lose right now, so
   //--- that even a full stop-out cannot breach the daily soft limit
   double            RemainingDailyRiskMoney(void) const;
   double            RemainingTotalRiskMoney(void) const;

   //--- trade accounting, driven from OnTradeTransaction / history scan
   void              RegisterOpen(void);
   void              RegisterClosedTrade(const double profit);

   //--- accessors
   int               TradesToday(void)        const { return m_tradesToday; }
   int               WinsToday(void)          const { return m_winsToday; }
   int               LossesToday(void)        const { return m_lossesToday; }
   int               ConsecutiveLosses(void)  const { return m_consecutiveLosses; }
   int               TradingDays(void)        const { return m_tradingDays; }
   bool              TargetReached(void)      const { return m_targetReached; }
   double            DayStartBalance(void)    const { return m_dayStartBalance; }
   double            RealisedToday(void)      const { return m_realisedToday; }
   string            LastReason(void)         const { return m_lastReason; }
   double            RiskFactor(void)         const;
   double            DailyDrawdownPct(void)   const;
   double            TotalDrawdownPct(void)   const;
   double            ProfitPct(void)          const;
   datetime          CurrentDayStart(void)    const { return m_currentDayStart; }
   void              SetCetOffset(const int s)      { m_cetOffsetSec = s; }
   void              SetTradingDays(const int d)    { m_tradingDays = MathMax(m_tradingDays, d); }
  };

//+------------------------------------------------------------------+
CRiskGuard::CRiskGuard(void)
  {
   m_initialCapital       = 0.0;
   m_dayStartBalance      = 0.0;
   m_dayStartEquity       = 0.0;
   m_currentDayStart      = 0;
   m_cetOffsetSec         = 0;
   m_ftmoDailyLossPct     = 5.0;
   m_ftmoMaxLossPct       = 10.0;
   m_softDailyLossPct     = 2.5;
   m_hardDailyLossPct     = 3.5;
   m_softTotalLossPct     = 6.0;
   m_hardTotalLossPct     = 8.0;
   m_profitTargetPct      = 10.0;
   m_stopAtTarget         = true;
   m_maxTradesPerDay      = 3;
   m_maxConsecutiveLosses = 3;
   m_lossStreakRiskFactor = 0.6;
   m_tradesToday          = 0;
   m_winsToday            = 0;
   m_lossesToday          = 0;
   m_consecutiveLosses    = 0;
   m_realisedToday        = 0.0;
   m_tradingDays          = 0;
   m_targetReached        = false;
   m_dayLockedOut         = false;
   m_lastReason           = "";
   m_magic                = 0;
   m_symbol               = "";
  }

//+------------------------------------------------------------------+
bool CRiskGuard::Init(const string symbol,
                      const ulong magic,
                      const double initialCapital,
                      const double ftmoDailyLossPct,
                      const double ftmoMaxLossPct,
                      const double softDailyLossPct,
                      const double hardDailyLossPct,
                      const double softTotalLossPct,
                      const double hardTotalLossPct,
                      const double profitTargetPct,
                      const bool   stopAtTarget,
                      const int    maxTradesPerDay,
                      const int    maxConsecutiveLosses,
                      const double lossStreakRiskFactor,
                      const int    cetOffsetSec)
  {
   m_symbol = symbol;
   m_magic  = magic;

   m_initialCapital = initialCapital;
   if(m_initialCapital <= 0.0)
      m_initialCapital = AccountInfoDouble(ACCOUNT_BALANCE);

   if(m_initialCapital <= 0.0)
     {
      Print("[Risk] FATAL: initial capital could not be determined.");
      return false;
     }

   m_ftmoDailyLossPct     = ftmoDailyLossPct;
   m_ftmoMaxLossPct       = ftmoMaxLossPct;
   m_softDailyLossPct     = softDailyLossPct;
   m_hardDailyLossPct     = hardDailyLossPct;
   m_softTotalLossPct     = softTotalLossPct;
   m_hardTotalLossPct     = hardTotalLossPct;
   m_profitTargetPct      = profitTargetPct;
   m_stopAtTarget         = stopAtTarget;
   m_maxTradesPerDay      = maxTradesPerDay;
   m_maxConsecutiveLosses = maxConsecutiveLosses;
   m_lossStreakRiskFactor = lossStreakRiskFactor;
   m_cetOffsetSec         = cetOffsetSec;

   // sanity: never let the soft guards sit above the real FTMO limits
   if(m_hardDailyLossPct >= m_ftmoDailyLossPct)
      m_hardDailyLossPct = m_ftmoDailyLossPct * 0.8;
   if(m_softDailyLossPct >= m_hardDailyLossPct)
      m_softDailyLossPct = m_hardDailyLossPct * 0.7;
   if(m_hardTotalLossPct >= m_ftmoMaxLossPct)
      m_hardTotalLossPct = m_ftmoMaxLossPct * 0.8;
   if(m_softTotalLossPct >= m_hardTotalLossPct)
      m_softTotalLossPct = m_hardTotalLossPct * 0.75;

   RollDay(TimeTradeServer());

   PrintFormat("[Risk] initial=%.2f  daily soft/hard=%.2f%%/%.2f%%  total soft/hard=%.2f%%/%.2f%%  target=%.2f%%",
               m_initialCapital, m_softDailyLossPct, m_hardDailyLossPct,
               m_softTotalLossPct, m_hardTotalLossPct, m_profitTargetPct);
   return true;
  }

//+------------------------------------------------------------------+
//| Starts a fresh trading day, anchored on 00:00 CE(S)T.            |
//+------------------------------------------------------------------+
void CRiskGuard::RollDay(const datetime serverNow)
  {
   datetime cetNow   = serverNow - (datetime)m_cetOffsetSec;
   datetime cetMid   = DayStart(cetNow);
   m_currentDayStart = cetMid + (datetime)m_cetOffsetSec;

   m_dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   m_dayStartEquity  = AccountInfoDouble(ACCOUNT_EQUITY);

   // FTMO measures the daily limit from the balance at 00:00 CE(S)T, but if
   // a position is carried over the floating loss already counts. Using the
   // lower of balance and equity is the conservative reading.
   if(m_dayStartEquity < m_dayStartBalance)
      m_dayStartBalance = m_dayStartEquity;

   m_tradesToday       = 0;
   m_winsToday         = 0;
   m_lossesToday       = 0;
   m_realisedToday     = 0.0;
   m_dayLockedOut      = false;

   PrintFormat("[Risk] new trading day from %s (server). Day-start balance %.2f",
               TimeToString(m_currentDayStart, TIME_DATE | TIME_MINUTES), m_dayStartBalance);
  }

//+------------------------------------------------------------------+
void CRiskGuard::OnTick(const datetime serverNow)
  {
   datetime cetNow = serverNow - (datetime)m_cetOffsetSec;
   datetime cetMid = DayStart(cetNow);
   datetime boundary = cetMid + (datetime)m_cetOffsetSec;

   if(boundary != m_currentDayStart)
      RollDay(serverNow);
  }

//+------------------------------------------------------------------+
double CRiskGuard::DailyDrawdownPct(void) const
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double loss   = m_dayStartBalance - equity;
   if(loss <= 0.0)
      return 0.0;
   return loss / m_initialCapital * 100.0;
  }

//+------------------------------------------------------------------+
double CRiskGuard::TotalDrawdownPct(void) const
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double loss   = m_initialCapital - equity;
   if(loss <= 0.0)
      return 0.0;
   return loss / m_initialCapital * 100.0;
  }

//+------------------------------------------------------------------+
double CRiskGuard::ProfitPct(void) const
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   return (equity - m_initialCapital) / m_initialCapital * 100.0;
  }

//+------------------------------------------------------------------+
//| The single most important method in the EA.                      |
//+------------------------------------------------------------------+
ENUM_GUARD_ACTION CRiskGuard::Evaluate(void)
  {
   double dailyDd = DailyDrawdownPct();
   double totalDd = TotalDrawdownPct();

   if(totalDd >= m_hardTotalLossPct)
     {
      m_lastReason = StringFormat("HARD total DD %.2f%% >= %.2f%% - flatten and stop", totalDd, m_hardTotalLossPct);
      return GUARD_HARD_FLAT;
     }

   if(dailyDd >= m_hardDailyLossPct)
     {
      m_lastReason = StringFormat("HARD daily DD %.2f%% >= %.2f%% - flatten for the day", dailyDd, m_hardDailyLossPct);
      m_dayLockedOut = true;
      return GUARD_HARD_FLAT;
     }

   if(totalDd >= m_softTotalLossPct)
     {
      m_lastReason = StringFormat("SOFT total DD %.2f%% - no new trades", totalDd);
      return GUARD_SOFT_HALT;
     }

   if(dailyDd >= m_softDailyLossPct)
     {
      m_lastReason = StringFormat("SOFT daily DD %.2f%% - no new trades today", dailyDd);
      m_dayLockedOut = true;
      return GUARD_SOFT_HALT;
     }

   if(m_stopAtTarget && ProfitPct() >= m_profitTargetPct)
     {
      m_targetReached = true;
      m_lastReason = StringFormat("Phase target %.2f%% reached - standing down", m_profitTargetPct);
      return GUARD_SOFT_HALT;
     }

   if(m_dayLockedOut)
     {
      m_lastReason = "Day locked out earlier";
      return GUARD_SOFT_HALT;
     }

   if(m_maxConsecutiveLosses > 0 && m_consecutiveLosses >= m_maxConsecutiveLosses)
     {
      m_lastReason = StringFormat("%d consecutive losses - paused for the day", m_consecutiveLosses);
      return GUARD_SOFT_HALT;
     }

   if(m_maxTradesPerDay > 0 && m_tradesToday >= m_maxTradesPerDay)
     {
      m_lastReason = StringFormat("Daily trade cap (%d) reached", m_maxTradesPerDay);
      return GUARD_SOFT_HALT;
     }

   m_lastReason = "OK";
   return GUARD_NONE;
  }

//+------------------------------------------------------------------+
//| Risk budget still available today before the SOFT daily guard.   |
//+------------------------------------------------------------------+
double CRiskGuard::RemainingDailyRiskMoney(void) const
  {
   double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
   double floorEq = m_dayStartBalance - PctOfInitial(m_softDailyLossPct);
   double room    = equity - floorEq;
   return MathMax(0.0, room);
  }

//+------------------------------------------------------------------+
double CRiskGuard::RemainingTotalRiskMoney(void) const
  {
   double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
   double floorEq = m_initialCapital - PctOfInitial(m_softTotalLossPct);
   double room    = equity - floorEq;
   return MathMax(0.0, room);
  }

//+------------------------------------------------------------------+
//| Risk multiplier applied after a losing streak. Cutting size on   |
//| a losing run is what keeps a bad week from becoming a breach.    |
//+------------------------------------------------------------------+
double CRiskGuard::RiskFactor(void) const
  {
   if(m_consecutiveLosses <= 1)
      return 1.0;
   double f = MathPow(m_lossStreakRiskFactor, (double)(m_consecutiveLosses - 1));
   return MathMax(0.25, f);
  }

//+------------------------------------------------------------------+
//| Position sizing.                                                 |
//| The lot is the SMALLEST of:                                      |
//|   a) the configured risk-per-trade,                              |
//|   b) whatever still fits under the daily soft guard,             |
//|   c) whatever still fits under the total soft guard.             |
//| That third clause is what stops a drawdown from compounding.     |
//+------------------------------------------------------------------+
double CRiskGuard::LotsForRisk(const double riskPercent,
                               const double stopDistancePrice,
                               const ENUM_RISK_MODE mode,
                               const double fixedLot,
                               string &reason)
  {
   reason = "";

   double minLot = SymbolInfoDouble(m_symbol, SYMBOL_VOLUME_MIN);

   if(mode == RISK_FIXED_LOT)
     {
      double fl = NormalizeVolume(m_symbol, fixedLot);
      if(fl <= 0.0)
         reason = StringFormat("fixed lot %.2f is below the broker minimum %.2f", fixedLot, minLot);
      return fl;
     }

   if(stopDistancePrice <= 0.0)
     {
      reason = "stop distance is zero";
      return 0.0;
     }

   double base = m_initialCapital;
   if(mode == RISK_PERCENT_BALANCE)
      base = AccountInfoDouble(ACCOUNT_BALANCE);
   else
      if(mode == RISK_PERCENT_EQUITY)
         base = AccountInfoDouble(ACCOUNT_EQUITY);

   double wanted = base * riskPercent / 100.0 * RiskFactor();

   // never risk more than the remaining room under either guard, with a
   // 30% cushion so slippage on the stop cannot push us through
   double dailyRoom = RemainingDailyRiskMoney() * 0.70;
   double totalRoom = RemainingTotalRiskMoney() * 0.70;

   double riskMoney = MathMin(wanted, MathMin(dailyRoom, totalRoom));

   if(riskMoney <= 0.0)
     {
      if(dailyRoom <= 0.0)
         reason = StringFormat("no daily risk budget left (soft guard at %.2f%%)", m_softDailyLossPct);
      else
         if(totalRoom <= 0.0)
            reason = StringFormat("no total risk budget left (soft guard at %.2f%%)", m_softTotalLossPct);
         else
            reason = "risk budget is zero";
      return 0.0;
     }

   if(riskMoney < wanted)
      PrintFormat("[Risk] sizing throttled: wanted %.2f, room allows %.2f (daily %.2f / total %.2f).",
                  wanted, riskMoney, dailyRoom, totalRoom);

   double moneyPerLot = MoneyForDistance(m_symbol, stopDistancePrice, 1.0);
   if(moneyPerLot <= 0.0)
     {
      reason = "the broker's tick value could not be converted to money";
      return 0.0;
    }

   double raw  = riskMoney / moneyPerLot;
   double lots = NormalizeVolume(m_symbol, raw);

   if(lots <= 0.0)
     {
      // The single most common reason a trade is skipped on a small account:
      // one minimum lot would risk more than the rules allow. Say so exactly,
      // with the numbers, rather than reporting a generic failure.
      double minLotRisk = MoneyForDistance(m_symbol, stopDistancePrice, minLot);
      double minLotPct  = (m_initialCapital > 0.0 ? minLotRisk / m_initialCapital * 100.0 : 0.0);
      reason = StringFormat("min lot %.2f would risk %.2f (%.2f%% of initial) but only %.2f "
                            "(%.2f%%) is allowed - raise InpRiskPercent, tighten the stop, "
                            "or trade a smaller account tier",
                            minLot, minLotRisk, minLotPct, riskMoney,
                            (m_initialCapital > 0.0 ? riskMoney / m_initialCapital * 100.0 : 0.0));
      return 0.0;
     }

   //--- margin sanity check
   double marginRequired = 0.0;
   double ask = SymbolInfoDouble(m_symbol, SYMBOL_ASK);
   if(OrderCalcMargin(ORDER_TYPE_BUY, m_symbol, lots, ask, marginRequired))
     {
      double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      if(marginRequired > freeMargin * 0.5)
        {
         reason = StringFormat("lot %.2f needs %.2f margin, only %.2f free (50%% cap)",
                               lots, marginRequired, freeMargin);
         return 0.0;
        }
     }
   else
      PrintFormat("[Risk] WARNING: OrderCalcMargin failed (error %d) - margin not verified.",
                  GetLastError());

   return lots;
  }

//+------------------------------------------------------------------+
void CRiskGuard::RegisterOpen(void)
  {
   m_tradesToday++;
   if(m_tradesToday == 1)
      m_tradingDays++;
  }

//+------------------------------------------------------------------+
void CRiskGuard::RegisterClosedTrade(const double profit)
  {
   m_realisedToday += profit;

   if(profit > 0.0)
     {
      m_winsToday++;
      m_consecutiveLosses = 0;
     }
   else
      if(profit < 0.0)
        {
         m_lossesToday++;
         m_consecutiveLosses++;
        }
  }

#endif // __XAUUSD_FTMO_RISKGUARD_MQH__
//+------------------------------------------------------------------+
