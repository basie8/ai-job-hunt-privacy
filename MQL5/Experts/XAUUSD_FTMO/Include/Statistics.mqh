//+------------------------------------------------------------------+
//|                                                   Statistics.mqh |
//|  Trade statistics for the console panel.                         |
//|                                                                  |
//|  Two families of metric are kept side by side:                   |
//|                                                                  |
//|    MONEY metrics  - available for every closed trade, including  |
//|                     trades rebuilt from the account history on   |
//|                     startup, so a terminal restart does not      |
//|                     reset the panel to zero.                     |
//|    R metrics      - only for trades this EA opened itself, where |
//|                     the risk at entry is known. Expectancy in R  |
//|                     is the number that actually tells you        |
//|                     whether the strategy has an edge, so it is   |
//|                     reported with its own sample count rather    |
//|                     than being estimated from money.             |
//+------------------------------------------------------------------+
#ifndef __XAUUSD_FTMO_STATISTICS_MQH__
#define __XAUUSD_FTMO_STATISTICS_MQH__

//--- version stamp. The EA checks for this, so copying a new .mq5
//--- next to a stale .mqh fails with one named error instead of forty.
#define XFC_V_STATISTICS_2

#include "CoreDefs.mqh"

//+------------------------------------------------------------------+
class CStatistics
  {
private:
   double            m_profit[];      // realised money per closed position
   double            m_risk[];        // risk at entry, 0 when unknown
   int               m_count;

   //--- money aggregates
   int               m_wins;
   int               m_losses;
   int               m_breakeven;
   double            m_grossProfit;
   double            m_grossLoss;     // stored positive
   double            m_largestWin;
   double            m_largestLoss;   // stored positive

   //--- R aggregates (subset where the risk is known)
   int               m_rSample;
   int               m_rWins;
   int               m_rLosses;
   double            m_rTotal;
   double            m_rWinTotal;
   double            m_rLossTotal;    // stored positive

   //--- streaks
   int               m_curStreak;     // >0 wins, <0 losses
   int               m_maxWinStreak;
   int               m_maxLossStreak;

   //--- closed-equity drawdown
   double            m_runningPnl;
   double            m_peakPnl;
   double            m_maxDrawdown;

public:
                     CStatistics(void) { Reset(); }

   void              Reset(void);
   void              Register(const double profit, const double riskMoney);
   int               RebuildFromHistory(const string symbol, const ulong magic, const datetime since);

   //--- counts
   int               Trades(void)          const { return m_count; }
   int               Wins(void)            const { return m_wins; }
   int               Losses(void)          const { return m_losses; }
   int               Breakeven(void)       const { return m_breakeven; }

   //--- headline ratios
   double            WinRate(void)         const;
   double            ProfitFactor(void)    const;
   double            AvgWin(void)          const;
   double            AvgLoss(void)         const;   // positive
   double            PayoffRatio(void)     const;   // avg win / avg loss
   double            Expectancy(void)      const;   // money per trade
   double            NetProfit(void)       const { return m_grossProfit - m_grossLoss; }
   double            LargestWin(void)      const { return m_largestWin; }
   double            LargestLoss(void)     const { return m_largestLoss; }

   //--- R metrics
   int               RSample(void)         const { return m_rSample; }
   double            TotalR(void)          const { return m_rTotal; }
   double            ExpectancyR(void)     const;
   double            AvgWinR(void)         const;
   double            AvgLossR(void)        const;   // positive

   //--- streaks and drawdown
   int               CurrentStreak(void)   const { return m_curStreak; }
   int               MaxWinStreak(void)    const { return m_maxWinStreak; }
   int               MaxLossStreak(void)   const { return m_maxLossStreak; }
   double            MaxDrawdown(void)     const { return m_maxDrawdown; }
  };

//+------------------------------------------------------------------+
void CStatistics::Reset(void)
  {
   ArrayResize(m_profit, 0);
   ArrayResize(m_risk, 0);
   m_count         = 0;
   m_wins          = 0;
   m_losses        = 0;
   m_breakeven     = 0;
   m_grossProfit   = 0.0;
   m_grossLoss     = 0.0;
   m_largestWin    = 0.0;
   m_largestLoss   = 0.0;
   m_rSample       = 0;
   m_rWins         = 0;
   m_rLosses       = 0;
   m_rTotal        = 0.0;
   m_rWinTotal     = 0.0;
   m_rLossTotal    = 0.0;
   m_curStreak     = 0;
   m_maxWinStreak  = 0;
   m_maxLossStreak = 0;
   m_runningPnl    = 0.0;
   m_peakPnl       = 0.0;
   m_maxDrawdown   = 0.0;
  }

//+------------------------------------------------------------------+
//| Records one fully closed position.                               |
//| 'riskMoney' is what the trade stood to lose at entry; pass 0     |
//| when it is not known (history rebuild) and the trade will be     |
//| counted in the money metrics only.                               |
//+------------------------------------------------------------------+
void CStatistics::Register(const double profit, const double riskMoney)
  {
   ArrayResize(m_profit, m_count + 1);
   ArrayResize(m_risk,   m_count + 1);
   m_profit[m_count] = profit;
   m_risk[m_count]   = riskMoney;
   m_count++;

   //--- money side
   if(profit > 0.0)
     {
      m_wins++;
      m_grossProfit += profit;
      if(profit > m_largestWin)
         m_largestWin = profit;

      m_curStreak = (m_curStreak > 0 ? m_curStreak + 1 : 1);
      if(m_curStreak > m_maxWinStreak)
         m_maxWinStreak = m_curStreak;
     }
   else
      if(profit < 0.0)
        {
         m_losses++;
         m_grossLoss += -profit;
         if(-profit > m_largestLoss)
            m_largestLoss = -profit;

         m_curStreak = (m_curStreak < 0 ? m_curStreak - 1 : -1);
         if(-m_curStreak > m_maxLossStreak)
            m_maxLossStreak = -m_curStreak;
        }
      else
         m_breakeven++;

   //--- R side, only when the entry risk is known
   if(riskMoney > 0.0)
     {
      double r = profit / riskMoney;
      m_rSample++;
      m_rTotal += r;
      if(r > 0.0)
        {
         m_rWins++;
         m_rWinTotal += r;
        }
      else
         if(r < 0.0)
           {
            m_rLosses++;
            m_rLossTotal += -r;
           }
     }

   //--- closed-equity drawdown
   m_runningPnl += profit;
   if(m_runningPnl > m_peakPnl)
      m_peakPnl = m_runningPnl;
   double dd = m_peakPnl - m_runningPnl;
   if(dd > m_maxDrawdown)
      m_maxDrawdown = dd;
  }

//+------------------------------------------------------------------+
double CStatistics::WinRate(void) const
  {
   int decided = m_wins + m_losses;
   if(decided <= 0)
      return 0.0;
   return (double)m_wins / (double)decided * 100.0;
  }

//+------------------------------------------------------------------+
double CStatistics::ProfitFactor(void) const
  {
   if(m_grossLoss <= 0.0)
      return (m_grossProfit > 0.0 ? 999.0 : 0.0);
   return m_grossProfit / m_grossLoss;
  }

//+------------------------------------------------------------------+
double CStatistics::AvgWin(void) const
  {
   if(m_wins <= 0)
      return 0.0;
   return m_grossProfit / (double)m_wins;
  }

//+------------------------------------------------------------------+
double CStatistics::AvgLoss(void) const
  {
   if(m_losses <= 0)
      return 0.0;
   return m_grossLoss / (double)m_losses;
  }

//+------------------------------------------------------------------+
double CStatistics::PayoffRatio(void) const
  {
   double al = AvgLoss();
   if(al <= 0.0)
      return (AvgWin() > 0.0 ? 999.0 : 0.0);
   return AvgWin() / al;
  }

//+------------------------------------------------------------------+
double CStatistics::Expectancy(void) const
  {
   if(m_count <= 0)
      return 0.0;
   return NetProfit() / (double)m_count;
  }

//+------------------------------------------------------------------+
double CStatistics::ExpectancyR(void) const
  {
   if(m_rSample <= 0)
      return 0.0;
   return m_rTotal / (double)m_rSample;
  }

//+------------------------------------------------------------------+
double CStatistics::AvgWinR(void) const
  {
   if(m_rWins <= 0)
      return 0.0;
   return m_rWinTotal / (double)m_rWins;
  }

//+------------------------------------------------------------------+
double CStatistics::AvgLossR(void) const
  {
   if(m_rLosses <= 0)
      return 0.0;
   return m_rLossTotal / (double)m_rLosses;
  }

//+------------------------------------------------------------------+
//| Rebuilds the money metrics from the account history so the panel |
//| survives a terminal restart mid-challenge.                       |
//|                                                                  |
//| Deals are grouped by position id, because a scaled-out trade     |
//| produces several exit deals that are one trade, not three.       |
//| Returns the number of positions reconstructed.                   |
//+------------------------------------------------------------------+
int CStatistics::RebuildFromHistory(const string symbol, const ulong magic, const datetime since)
  {
   if(!HistorySelect(since, TimeCurrent() + 86400))
      return 0;

   int total = HistoryDealsTotal();
   if(total <= 0)
      return 0;

   ulong  ids[];
   double sums[];
   long   closeTimes[];
   int    n = 0;

   for(int i = 0; i < total; i++)
     {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0)
         continue;

      if(HistoryDealGetString(deal, DEAL_SYMBOL) != symbol)
         continue;
      if((ulong)HistoryDealGetInteger(deal, DEAL_MAGIC) != magic)
         continue;

      ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY)
         continue;

      ulong  posId  = (ulong)HistoryDealGetInteger(deal, DEAL_POSITION_ID);
      long   tm     = (long)HistoryDealGetInteger(deal, DEAL_TIME);
      double profit = HistoryDealGetDouble(deal, DEAL_PROFIT)
                      + HistoryDealGetDouble(deal, DEAL_SWAP)
                      + HistoryDealGetDouble(deal, DEAL_COMMISSION);

      int idx = -1;
      for(int k = 0; k < n; k++)
        {
         if(ids[k] == posId)
           {
            idx = k;
            break;
           }
        }

      if(idx < 0)
        {
         ArrayResize(ids, n + 1);
         ArrayResize(sums, n + 1);
         ArrayResize(closeTimes, n + 1);
         ids[n]        = posId;
         sums[n]       = 0.0;
         closeTimes[n] = tm;
         idx = n;
         n++;
        }

      sums[idx] += profit;
      if(tm > closeTimes[idx])
         closeTimes[idx] = tm;
     }

   //--- register in close-time order so the streak and drawdown figures
   //--- reflect the real sequence of events
   for(int a = 1; a < n; a++)
     {
      long   kt = closeTimes[a];
      double ks = sums[a];
      ulong  ki = ids[a];
      int b = a - 1;
      while(b >= 0 && closeTimes[b] > kt)
        {
         closeTimes[b + 1] = closeTimes[b];
         sums[b + 1]       = sums[b];
         ids[b + 1]        = ids[b];
         b--;
        }
      closeTimes[b + 1] = kt;
      sums[b + 1]       = ks;
      ids[b + 1]        = ki;
     }

   for(int c = 0; c < n; c++)
      Register(sums[c], 0.0);      // risk unknown for historical trades

   return n;
  }

#endif // __XAUUSD_FTMO_STATISTICS_MQH__
//+------------------------------------------------------------------+
