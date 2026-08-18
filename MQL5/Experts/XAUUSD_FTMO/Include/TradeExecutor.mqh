//+------------------------------------------------------------------+
//|                                                TradeExecutor.mqh |
//|  Order placement and the trade-management state machine.         |
//|                                                                  |
//|  THE ASYMMETRY ENGINE                                            |
//|  ------------------------------------------------------------    |
//|  The brief asks for a high proportion of green trades AND wins   |
//|  that dwarf losses. Those two pull in opposite directions if a   |
//|  trade has a single exit, so every position is scaled out:       |
//|                                                                  |
//|    entry ---> TP1 at 1R      : close PartialPct of the position  |
//|                                and pull the stop to breakeven +  |
//|                                a small lock. From this point the |
//|                                trade CANNOT lose.                |
//|          ---> 1.5R           : ATR chandelier trail engages      |
//|          ---> TP2 at 3R      : runner closes                     |
//|                                                                  |
//|  Outcomes:  full stop        = -1.00R                            |
//|             TP1 then BE      = +0.50R  (counts as a win)         |
//|             TP1 then trail   = +0.5R .. +2.0R                    |
//|             TP1 then TP2     = +2.00R                            |
//|                                                                  |
//|  So the average win is a multiple of the average loss even when  |
//|  most trades only reach the first target.                        |
//+------------------------------------------------------------------+
#ifndef __XAUUSD_FTMO_TRADEEXECUTOR_MQH__
#define __XAUUSD_FTMO_TRADEEXECUTOR_MQH__

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include "CoreDefs.mqh"

//+------------------------------------------------------------------+
class CTradeExecutor
  {
private:
   CTrade            m_trade;
   CPositionInfo     m_pos;

   string            m_symbol;
   ENUM_TIMEFRAMES   m_tf;
   ulong             m_magic;
   int               m_slippagePoints;
   bool              m_verbose;

   //--- management parameters
   double            m_tp1R;               // R multiple at which the partial fires
   double            m_partialPct;         // % of the position closed at TP1
   double            m_beLockR;            // stop parked this many R beyond entry
   double            m_trailStartR;        // trail engages after this many R
   double            m_trailAtrMult;       // chandelier distance in ATR
   double            m_trailStepPrice;     // minimum stop improvement before a modify
   int               m_trailLookback;      // bars used for the chandelier extreme
   bool              m_usePartial;
   bool              m_useTrail;

   //--- per-position state, keyed by ticket
   ulong             m_tickets[];
   double            m_entryPrice[];
   double            m_initialRisk[];
   double            m_initialVolume[];
   int               m_stage[];            // 0 = fresh, 1 = TP1 done, 2 = trailing
   int               m_count;

   int               IndexOf(const ulong ticket);
   string            StateKey(const ulong ticket, const string field);
   void              PersistState(const int idx);
   void              ClearState(const ulong ticket);
   bool              RestoreState(const ulong ticket, double &entry, double &risk, int &stage);
   void              Track(const ulong ticket, const double entry, const double risk, const double volume);
   void              Untrack(const int idx);
   double            ChandelierStop(const ENUM_POSITION_TYPE type, const double atr);

public:
                     CTradeExecutor(void);

   bool              Init(const string symbol,
                          const ENUM_TIMEFRAMES tf,
                          const ulong magic,
                          const int slippagePoints,
                          const bool verbose);

   void              SetManagement(const double tp1R,
                                   const double partialPct,
                                   const double beLockR,
                                   const double trailStartR,
                                   const double trailAtrMult,
                                   const double trailStepPrice,
                                   const int    trailLookback,
                                   const bool   usePartial,
                                   const bool   useTrail);

   //--- returns the ticket, or 0 on failure
   ulong             OpenTrade(const ENUM_SIGNAL_DIR dir,
                               const double lots,
                               const double stop,
                               const double takeProfit,
                               const string comment);

   //--- run every tick: partials, breakeven, trailing
   void              Manage(const double atr);

   //--- emergency
   int               CloseAll(const string why);

   int               OpenPositions(void);
   bool              HasOpenPosition(void);
   double            OpenRiskMoney(void);
   void              SyncFromTerminal(void);
   string            StateText(void);
  };

//+------------------------------------------------------------------+
CTradeExecutor::CTradeExecutor(void)
  {
   m_symbol         = "";
   m_tf             = PERIOD_CURRENT;
   m_magic          = 0;
   m_slippagePoints = 30;
   m_verbose        = false;
   m_tp1R           = 1.0;
   m_partialPct     = 50.0;
   m_beLockR        = 0.10;
   m_trailStartR    = 1.5;
   m_trailAtrMult   = 2.0;
   m_trailStepPrice = 0.20;
   m_trailLookback  = 10;
   m_usePartial     = true;
   m_useTrail       = true;
   m_count          = 0;
  }

//+------------------------------------------------------------------+
bool CTradeExecutor::Init(const string symbol,
                          const ENUM_TIMEFRAMES tf,
                          const ulong magic,
                          const int slippagePoints,
                          const bool verbose)
  {
   m_symbol         = symbol;
   m_tf             = tf;
   m_magic          = magic;
   m_slippagePoints = slippagePoints;
   m_verbose        = verbose;

   m_trade.SetExpertMagicNumber(m_magic);
   m_trade.SetDeviationInPoints(m_slippagePoints);
   m_trade.SetTypeFillingBySymbol(m_symbol);
   m_trade.SetAsyncMode(false);
   m_trade.LogLevel(LOG_LEVEL_ERRORS);

   ArrayResize(m_tickets, 0);
   ArrayResize(m_entryPrice, 0);
   ArrayResize(m_initialRisk, 0);
   ArrayResize(m_initialVolume, 0);
   ArrayResize(m_stage, 0);
   m_count = 0;

   SyncFromTerminal();
   return true;
  }

//+------------------------------------------------------------------+
void CTradeExecutor::SetManagement(const double tp1R,
                                   const double partialPct,
                                   const double beLockR,
                                   const double trailStartR,
                                   const double trailAtrMult,
                                   const double trailStepPrice,
                                   const int    trailLookback,
                                   const bool   usePartial,
                                   const bool   useTrail)
  {
   m_tp1R          = MathMax(0.1, tp1R);
   m_partialPct    = MathMax(0.0, MathMin(90.0, partialPct));
   m_beLockR       = beLockR;
   m_trailStartR   = trailStartR;
   m_trailAtrMult   = trailAtrMult;
   m_trailStepPrice = MathMax(0.0, trailStepPrice);
   m_trailLookback = MathMax(3, trailLookback);
   m_usePartial    = usePartial;
   m_useTrail      = useTrail;
  }

//+------------------------------------------------------------------+
//| Per-position state survives a terminal restart.                  |
//|                                                                  |
//| Without this, adopting an open position after a restart had to   |
//| guess its original risk from the current stop distance. Once the |
//| stop is at breakeven that distance is a fraction of the real     |
//| risk, so the computed R multiple was inflated by roughly ten     |
//| times and the EA would immediately take a second scale-out on a  |
//| trade it had already managed.                                    |
//+------------------------------------------------------------------+
string CTradeExecutor::StateKey(const ulong ticket, const string field)
  {
   return StringFormat("XFC%I64u_%I64u_%s", m_magic, ticket, field);
  }

//+------------------------------------------------------------------+
void CTradeExecutor::PersistState(const int idx)
  {
   if(idx < 0 || idx >= m_count)
      return;
   ulong t = m_tickets[idx];
   GlobalVariableSet(StateKey(t, "e"), m_entryPrice[idx]);
   GlobalVariableSet(StateKey(t, "r"), m_initialRisk[idx]);
   GlobalVariableSet(StateKey(t, "s"), (double)m_stage[idx]);
  }

//+------------------------------------------------------------------+
void CTradeExecutor::ClearState(const ulong ticket)
  {
   GlobalVariableDel(StateKey(ticket, "e"));
   GlobalVariableDel(StateKey(ticket, "r"));
   GlobalVariableDel(StateKey(ticket, "s"));
  }

//+------------------------------------------------------------------+
bool CTradeExecutor::RestoreState(const ulong ticket, double &entry, double &risk, int &stage)
  {
   if(!GlobalVariableCheck(StateKey(ticket, "r")))
      return false;

   entry = GlobalVariableGet(StateKey(ticket, "e"));
   risk  = GlobalVariableGet(StateKey(ticket, "r"));
   stage = (int)GlobalVariableGet(StateKey(ticket, "s"));

   return (risk > 0.0 && entry > 0.0);
  }

//+------------------------------------------------------------------+
int CTradeExecutor::IndexOf(const ulong ticket)
  {
   for(int i = 0; i < m_count; i++)
      if(m_tickets[i] == ticket)
         return i;
   return -1;
  }

//+------------------------------------------------------------------+
void CTradeExecutor::Track(const ulong ticket, const double entry, const double risk, const double volume)
  {
   if(IndexOf(ticket) >= 0)
      return;
   ArrayResize(m_tickets,       m_count + 1);
   ArrayResize(m_entryPrice,    m_count + 1);
   ArrayResize(m_initialRisk,   m_count + 1);
   ArrayResize(m_initialVolume, m_count + 1);
   ArrayResize(m_stage,         m_count + 1);

   m_tickets[m_count]       = ticket;
   m_entryPrice[m_count]    = entry;
   m_initialRisk[m_count]   = risk;
   m_initialVolume[m_count] = volume;
   m_stage[m_count]         = 0;
   m_count++;

   PersistState(m_count - 1);
  }

//+------------------------------------------------------------------+
void CTradeExecutor::Untrack(const int idx)
  {
   if(idx < 0 || idx >= m_count)
      return;

   ClearState(m_tickets[idx]);

   for(int i = idx; i < m_count - 1; i++)
     {
      m_tickets[i]       = m_tickets[i + 1];
      m_entryPrice[i]    = m_entryPrice[i + 1];
      m_initialRisk[i]   = m_initialRisk[i + 1];
      m_initialVolume[i] = m_initialVolume[i + 1];
      m_stage[i]         = m_stage[i + 1];
     }
   m_count--;
   ArrayResize(m_tickets,       m_count);
   ArrayResize(m_entryPrice,    m_count);
   ArrayResize(m_initialRisk,   m_count);
   ArrayResize(m_initialVolume, m_count);
   ArrayResize(m_stage,         m_count);
  }

//+------------------------------------------------------------------+
//| Rebuilds the tracking table from live positions. Called on init  |
//| so a terminal restart does not orphan an open trade.             |
//+------------------------------------------------------------------+
void CTradeExecutor::SyncFromTerminal(void)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!m_pos.SelectByIndex(i))
         continue;
      if(m_pos.Symbol() != m_symbol || m_pos.Magic() != (long)m_magic)
         continue;

      ulong ticket = m_pos.Ticket();
      if(IndexOf(ticket) >= 0)
         continue;

      double entry = m_pos.PriceOpen();
      double sl    = m_pos.StopLoss();
      bool   isBuy = (m_pos.PositionType() == POSITION_TYPE_BUY);

      double savedEntry = 0.0, savedRisk = 0.0;
      int    savedStage = 0;

      if(RestoreState(ticket, savedEntry, savedRisk, savedStage))
        {
         Track(ticket, savedEntry, savedRisk, m_pos.Volume());
         int idx = IndexOf(ticket);
         if(idx >= 0)
           {
            m_stage[idx] = savedStage;
            PersistState(idx);
           }
         PrintFormat("[Exec] adopted position #%I64u from saved state: entry=%.2f risk=%.2f stage=%d",
                     ticket, savedEntry, savedRisk, savedStage);
         continue;
        }

      // No saved state (EA added to an existing position, or the variable
      // expired). Reconstruct conservatively.
      double risk = (sl > 0.0 ? MathAbs(entry - sl) : 0.0);

      // A stop already on the profitable side means this trade has been
      // through the breakeven step, so the distance to it is NOT the
      // original risk. Treat it as already protected and do not re-scale.
      bool alreadyProtected = (sl > 0.0 && (isBuy ? sl >= entry : sl <= entry));

      Track(ticket, entry, risk, m_pos.Volume());
      int idx2 = IndexOf(ticket);
      if(idx2 >= 0 && alreadyProtected)
        {
         m_stage[idx2] = 2;
         PersistState(idx2);
        }

      PrintFormat("[Exec] adopted position #%I64u with no saved state: entry=%.2f risk=%.2f%s",
                  ticket, entry, risk,
                  (alreadyProtected ? " (stop already beyond entry - treated as protected, no further scale-out)" : ""));
     }
  }

//+------------------------------------------------------------------+
ulong CTradeExecutor::OpenTrade(const ENUM_SIGNAL_DIR dir,
                                const double lots,
                                const double stop,
                                const double takeProfit,
                                const string comment)
  {
   if(dir == SIGNAL_NONE || lots <= 0.0)
      return 0;

   double ask = SymbolInfoDouble(m_symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(m_symbol, SYMBOL_BID);
   double price = (dir == SIGNAL_BUY ? ask : bid);

   bool ok = false;
   if(dir == SIGNAL_BUY)
      ok = m_trade.Buy(lots, m_symbol, 0.0, stop, takeProfit, comment);
   else
      ok = m_trade.Sell(lots, m_symbol, 0.0, stop, takeProfit, comment);

   if(!ok)
     {
      PrintFormat("[Exec] order REJECTED: retcode=%d (%s) lots=%.2f sl=%.2f tp=%.2f",
                  m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription(), lots, stop, takeProfit);
      return 0;
     }

   ulong ticket = m_trade.ResultDeal();
   double fillPrice = m_trade.ResultPrice();
   if(fillPrice <= 0.0)
      fillPrice = price;

   // resolve the POSITION ticket (the deal ticket is not the position id)
   ulong positionTicket = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!m_pos.SelectByIndex(i))
         continue;
      if(m_pos.Symbol() == m_symbol && m_pos.Magic() == (long)m_magic)
        {
         if(IndexOf(m_pos.Ticket()) < 0)
           {
            positionTicket = m_pos.Ticket();
            fillPrice = m_pos.PriceOpen();
            break;
           }
        }
     }
   if(positionTicket == 0)
     {
      // under hedging the position id equals the opening order ticket
      positionTicket = m_trade.ResultOrder();
      if(positionTicket == 0)
         positionTicket = ticket;
     }

   double risk = MathAbs(fillPrice - stop);
   Track(positionTicket, fillPrice, risk, lots);

   PrintFormat("[Exec] %s %.2f lots @ %.2f  SL=%.2f (%.2f risk)  TP=%.2f  | %s",
               (dir == SIGNAL_BUY ? "BUY" : "SELL"), lots, fillPrice, stop, risk, takeProfit, comment);

   return positionTicket;
  }

//+------------------------------------------------------------------+
//| Highest high / lowest low based trailing stop.                   |
//+------------------------------------------------------------------+
double CTradeExecutor::ChandelierStop(const ENUM_POSITION_TYPE type, const double atr)
  {
   if(atr <= 0.0)
      return 0.0;

   if(type == POSITION_TYPE_BUY)
     {
      double highs[];
      ArraySetAsSeries(highs, true);
      if(CopyHigh(m_symbol, m_tf, 0, m_trailLookback, highs) < m_trailLookback)
         return 0.0;
      int idx = ArrayMaximum(highs, 0, m_trailLookback);
      if(idx < 0)
         return 0.0;
      return highs[idx] - atr * m_trailAtrMult;
     }

   double lows[];
   ArraySetAsSeries(lows, true);
   if(CopyLow(m_symbol, m_tf, 0, m_trailLookback, lows) < m_trailLookback)
      return 0.0;
   int idx2 = ArrayMinimum(lows, 0, m_trailLookback);
   if(idx2 < 0)
      return 0.0;
   return lows[idx2] + atr * m_trailAtrMult;
  }

//+------------------------------------------------------------------+
//| The management state machine, run on every tick.                 |
//|                                                                  |
//| STAGES - each one is a distinct concern, which matters because   |
//| they can fail independently:                                     |
//|                                                                  |
//|   0  fresh          waiting for price to reach TP1               |
//|   1  partial done   the scale-out is a ONE-SHOT and never        |
//|                     repeats, whatever happens afterwards         |
//|   2  breakeven set  the stop is protected; retried every tick    |
//|                     until it succeeds, because a breakeven that  |
//|                     failed silently is a full stop pretending    |
//|                     to be a free trade                           |
//|   3  trailing       the chandelier is active                     |
//|                                                                  |
//| Keeping the partial and the breakeven in one stage was a real    |
//| defect: a broker rejecting the stop modify left the stage at 0,  |
//| so the next tick took ANOTHER partial, and the position was      |
//| scaled out of existence one tick at a time.                      |
//+------------------------------------------------------------------+
void CTradeExecutor::Manage(const double atr)
  {
   // drop tickets that no longer exist
   for(int i = m_count - 1; i >= 0; i--)
     {
      if(!PositionSelectByTicket(m_tickets[i]))
         Untrack(i);
     }

   // A modify must clear BOTH the stops level and the freeze level. Ignoring
   // the freeze level is a classic source of modifications that fail on some
   // brokers with no obvious reason.
   long   stopLevelPts   = SymbolInfoInteger(m_symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long   freezeLevelPts = SymbolInfoInteger(m_symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double point          = SymbolInfoDouble(m_symbol, SYMBOL_POINT);
   double minDistance    = (double)MathMax(stopLevelPts, freezeLevelPts) * point;
   double minLot         = SymbolInfoDouble(m_symbol, SYMBOL_VOLUME_MIN);

   for(int i = m_count - 1; i >= 0; i--)
     {
      ulong ticket = m_tickets[i];
      if(!m_pos.SelectByTicket(ticket))
         continue;

      ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)m_pos.PositionType();
      bool   isBuy  = (type == POSITION_TYPE_BUY);
      double entry  = m_entryPrice[i];
      double risk   = m_initialRisk[i];
      double curSl  = m_pos.StopLoss();
      double curTp  = m_pos.TakeProfit();
      double volume = m_pos.Volume();

      if(risk <= 0.0)
         continue;

      double bid = SymbolInfoDouble(m_symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(m_symbol, SYMBOL_ASK);
      double favourable = (isBuy ? (bid - entry) : (entry - ask));
      double rMultiple  = favourable / risk;
      double lock       = risk * m_beLockR;

      //--------------------------------------------------------------
      // STAGE 0 : the scale-out. One shot, then the stage always
      //           advances so it can never repeat.
      //--------------------------------------------------------------
      if(m_stage[i] == 0)
        {
         if(rMultiple < m_tp1R)
            continue;                       // TP1 not reached yet

         if(m_usePartial)
           {
            double closeVol = NormalizeVolume(m_symbol, volume * m_partialPct / 100.0);
            double remain   = NormalizeVolume(m_symbol, volume - closeVol);

            if(closeVol >= minLot && remain >= minLot)
              {
               if(m_trade.PositionClosePartial(ticket, closeVol))
                  PrintFormat("[Exec] #%I64u TP1 (%.2fR) hit at %.2fR - banked %.2f lots, %.2f runs on",
                              ticket, m_tp1R, rMultiple, closeVol, remain);
               else
                  PrintFormat("[Exec] #%I64u partial close FAILED: %s - the whole position runs on.",
                              ticket, m_trade.ResultRetcodeDescription());
              }
            else
               PrintFormat("[Exec] #%I64u no partial at %.2fR: %.2f lots will not split into two "
                           "parts of at least %.2f. The whole position runs to TP2.",
                           ticket, rMultiple, volume, minLot);
           }

         m_stage[i] = 1;
         PersistState(i);

         if(m_pos.SelectByTicket(ticket))     // refresh after a partial close
           {
            volume = m_pos.Volume();
            curSl  = m_pos.StopLoss();
            curTp  = m_pos.TakeProfit();
           }
        }

      //--------------------------------------------------------------
      // STAGE 1 : breakeven. Retried every tick until the stop is
      //           genuinely protected.
      //--------------------------------------------------------------
      if(m_stage[i] == 1)
        {
         double newSl = NormalizePriceToTick(m_symbol, (isBuy ? entry + lock : entry - lock));

         bool alreadyProtected = (curSl > 0.0 &&
                                  (isBuy ? curSl >= newSl - point : curSl <= newSl + point));

         if(alreadyProtected)
           {
            m_stage[i] = 2;
            PersistState(i);
           }
         else
           {
            bool distanceOk = (isBuy ? (bid - newSl) > minDistance : (newSl - ask) > minDistance);

            if(!distanceOk)
               PrintFormat("[Exec] #%I64u breakeven deferred: %.2f is inside the broker's %.2f "
                           "stop/freeze distance from %.2f - retrying.",
                           ticket, newSl, minDistance, (isBuy ? bid : ask));
            else
               if(m_trade.PositionModify(ticket, newSl, curTp))
                 {
                  m_stage[i] = 2;
                  PersistState(i);
                  curSl = newSl;
                  PrintFormat("[Exec] #%I64u stop moved to breakeven+%.2f (%.2f) - trade is now free.",
                              ticket, lock, newSl);
                 }
               else
                  PrintFormat("[Exec] #%I64u breakeven move FAILED (%s) - retrying next tick.",
                              ticket, m_trade.ResultRetcodeDescription());
           }

         if(m_stage[i] < 2)
            continue;                        // do not trail an unprotected trade
        }

      //--------------------------------------------------------------
      // STAGE 2+ : chandelier trail on the runner
      //--------------------------------------------------------------
      if(!m_useTrail || rMultiple < m_trailStartR)
         continue;

      double trail = ChandelierStop(type, atr);
      if(trail <= 0.0)
         continue;

      trail = NormalizePriceToTick(m_symbol, trail);

      // The step gate. Without it the chandelier issues a modify on every
      // tick that improves the stop by even one point, which brokers
      // throttle and which buries the journal.
      bool beatsStep = (curSl <= 0.0) ||
                       (isBuy ? (trail > curSl + m_trailStepPrice)
                              : (trail < curSl - m_trailStepPrice));

      bool distanceOk = (isBuy ? (bid - trail) > minDistance : (trail - ask) > minDistance);

      // never trail back behind the breakeven lock
      bool beyondLock = (isBuy ? (trail >= entry + lock) : (trail <= entry - lock));

      if(!(beatsStep && distanceOk && beyondLock))
         continue;

      if(m_trade.PositionModify(ticket, trail, curTp))
        {
         if(m_stage[i] < 3)
           {
            m_stage[i] = 3;
            PrintFormat("[Exec] #%I64u trailing engaged at %.2fR, stop %.2f", ticket, rMultiple, trail);
           }
         else
            if(m_verbose)
               PrintFormat("[Exec] #%I64u trail -> %.2f (at %.2fR)", ticket, trail, rMultiple);
         PersistState(i);
        }
      else
         PrintFormat("[Exec] #%I64u trail update to %.2f FAILED: %s",
                     ticket, trail, m_trade.ResultRetcodeDescription());
     }
  }

//+------------------------------------------------------------------+
int CTradeExecutor::CloseAll(const string why)
  {
   int closed = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!m_pos.SelectByIndex(i))
         continue;
      if(m_pos.Symbol() != m_symbol || m_pos.Magic() != (long)m_magic)
         continue;

      ulong ticket = m_pos.Ticket();
      if(m_trade.PositionClose(ticket))
        {
         closed++;
         PrintFormat("[Exec] closed #%I64u - %s", ticket, why);
        }
      else
         PrintFormat("[Exec] FAILED to close #%I64u: %s", ticket, m_trade.ResultRetcodeDescription());
     }

   for(int i = m_count - 1; i >= 0; i--)
      if(!PositionSelectByTicket(m_tickets[i]))
         Untrack(i);

   return closed;
  }

//+------------------------------------------------------------------+
int CTradeExecutor::OpenPositions(void)
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!m_pos.SelectByIndex(i))
         continue;
      if(m_pos.Symbol() == m_symbol && m_pos.Magic() == (long)m_magic)
         n++;
     }
   return n;
  }

//+------------------------------------------------------------------+
bool CTradeExecutor::HasOpenPosition(void)
  {
   return (OpenPositions() > 0);
  }

//+------------------------------------------------------------------+
//| Money currently at risk across all open positions of this EA.    |
//+------------------------------------------------------------------+
double CTradeExecutor::OpenRiskMoney(void)
  {
   double total = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!m_pos.SelectByIndex(i))
         continue;
      if(m_pos.Symbol() != m_symbol || m_pos.Magic() != (long)m_magic)
         continue;

      double sl = m_pos.StopLoss();
      if(sl <= 0.0)
         continue;

      double cur = m_pos.PriceCurrent();
      double distance = (m_pos.PositionType() == POSITION_TYPE_BUY ? (cur - sl) : (sl - cur));
      if(distance > 0.0)
         total += MoneyForDistance(m_symbol, distance, m_pos.Volume());
     }
   return total;
  }

//+------------------------------------------------------------------+
string CTradeExecutor::StateText(void)
  {
   if(m_count == 0)
      return "flat";
   string t = "";
   for(int i = 0; i < m_count; i++)
      t += StringFormat("#%I64u stage%d ", m_tickets[i], m_stage[i]);
   return t;
  }

#endif // __XAUUSD_FTMO_TRADEEXECUTOR_MQH__
//+------------------------------------------------------------------+
