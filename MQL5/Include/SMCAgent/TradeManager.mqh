//+------------------------------------------------------------------+
//|                                                 TradeManager.mqh |
//|                                                                  |
//|  Execution, in-trade management, and the two feedback books the   |
//|  learner is trained from:                                        |
//|    - CTradeJournal : real positions, resolved from history        |
//|    - CVirtualBook  : paper setups tracked bar by bar, used during |
//|                      the warm-up observation phase and for every  |
//|                      setup that was rejected by a guard rail, so  |
//|                      the agent keeps learning while it waits      |
//+------------------------------------------------------------------+
#ifndef __SMC_TRADEMANAGER_MQH__
#define __SMC_TRADEMANAGER_MQH__

#include <Trade/Trade.mqh>
#include "Defs.mqh"
#include "Logger.mqh"
#include "Learner.mqh"

//+------------------------------------------------------------------+
//| Resolved outcome handed back to the learner                      |
//+------------------------------------------------------------------+
struct SOutcome
  {
   double            y;            // 1 = objective reached, 0 = invalidated
   double            r_multiple;
   double            profit;
   bool              real_trade;
  };

//+------------------------------------------------------------------+
//| Real position journal                                            |
//+------------------------------------------------------------------+
class CTradeJournal
  {
private:
   ulong             m_ticket[];
   ulong             m_posid[];     // POSITION_IDENTIFIER: the key history is indexed by
   int               m_fails[];     // consecutive failed attempts to resolve the outcome
   double            m_x[];         // flattened feature vectors
   double            m_entry[];
   double            m_sl[];
   double            m_tp1[];
   int               m_dir[];
   datetime          m_open[];
   bool              m_partial[];
   bool              m_be[];
   int               m_meta[];      // SMC_META_* structural context at entry
   int               m_n;           // feature count

public:
                     CTradeJournal(void): m_n(0) {}

   void              Init(const int features) { m_n=features; }

   void              Add(const ulong ticket,const ulong position_id,const double &x[],const double entry,
                         const double sl,const double tp1,const int dir,const int meta=0)
     {
      int k=ArraySize(m_ticket);
      ArrayResize(m_ticket,k+1);
      ArrayResize(m_posid,k+1);
      ArrayResize(m_fails,k+1);
      ArrayResize(m_entry,k+1);
      ArrayResize(m_sl,k+1);
      ArrayResize(m_tp1,k+1);
      ArrayResize(m_dir,k+1);
      ArrayResize(m_open,k+1);
      ArrayResize(m_partial,k+1);
      ArrayResize(m_be,k+1);
      ArrayResize(m_meta,k+1);
      ArrayResize(m_x,(k+1)*m_n);
      m_meta[k]=meta;
      m_ticket[k]=ticket;
      m_posid[k]=(position_id>0?position_id:ticket);
      m_fails[k]=0;
      m_entry[k]=entry;
      m_sl[k]=sl;
      m_tp1[k]=tp1;
      m_dir[k]=dir;
      m_open[k]=SmcNow();
      m_partial[k]=false;
      m_be[k]=false;
      for(int i=0;i<m_n;i++) m_x[k*m_n+i]=(i<ArraySize(x)?x[i]:0.0);
     }

   int               Count(void) { return(ArraySize(m_ticket)); }
   int               Meta(const int i) { return(i>=0 && i<ArraySize(m_meta)?m_meta[i]:0); }
   ulong             Ticket(const int i) { return(i>=0 && i<ArraySize(m_ticket)?m_ticket[i]:0); }
   ulong             PositionId(const int i) { return(i>=0 && i<ArraySize(m_posid)?m_posid[i]:0); }
   int               Fails(const int i) { return(i>=0 && i<ArraySize(m_fails)?m_fails[i]:0); }
   void              MarkFail(const int i) { if(i>=0 && i<ArraySize(m_fails)) m_fails[i]++; }
   double            Entry(const int i)  { return(i>=0 && i<ArraySize(m_entry)?m_entry[i]:0.0); }
   double            Sl(const int i)     { return(i>=0 && i<ArraySize(m_sl)?m_sl[i]:0.0); }
   double            Tp1(const int i)    { return(i>=0 && i<ArraySize(m_tp1)?m_tp1[i]:0.0); }
   int               Dir(const int i)    { return(i>=0 && i<ArraySize(m_dir)?m_dir[i]:0); }
   datetime          Opened(const int i) { return(i>=0 && i<ArraySize(m_open)?m_open[i]:0); }
   bool              PartialDone(const int i) { return(i>=0 && i<ArraySize(m_partial)?m_partial[i]:true); }
   void              SetPartial(const int i)  { if(i>=0 && i<ArraySize(m_partial)) m_partial[i]=true; }
   bool              BeDone(const int i) { return(i>=0 && i<ArraySize(m_be)?m_be[i]:true); }
   void              SetBe(const int i)  { if(i>=0 && i<ArraySize(m_be)) m_be[i]=true; }

   void              Vector(const int i,double &dst[])
     {
      ArrayResize(dst,m_n);
      for(int f=0;f<m_n;f++) dst[f]=m_x[i*m_n+f];
     }

   int               IndexOf(const ulong ticket)
     {
      for(int i=0;i<ArraySize(m_ticket);i++) if(m_ticket[i]==ticket) return(i);
      return(-1);
     }

   void              Remove(const int i)
     {
      int k=ArraySize(m_ticket);
      if(i<0 || i>=k) return;
      ArrayRemove(m_x,i*m_n,m_n);
      ArrayRemove(m_ticket,i,1);
      ArrayRemove(m_posid,i,1);
      ArrayRemove(m_fails,i,1);
      ArrayRemove(m_entry,i,1);
      ArrayRemove(m_sl,i,1);
      ArrayRemove(m_tp1,i,1);
      ArrayRemove(m_dir,i,1);
      ArrayRemove(m_open,i,1);
      ArrayRemove(m_partial,i,1);
      ArrayRemove(m_be,i,1);
      ArrayRemove(m_meta,i,1);
     }
  };

//+------------------------------------------------------------------+
//| Paper trade book - the observation loop of the agent             |
//+------------------------------------------------------------------+
#define VB_MAX 60

class CVirtualBook
  {
private:
   int               m_n;
   double            m_x[];
   double            m_entry[];
   double            m_sl[];
   double            m_tp[];
   double            m_lots[];      // >0 for a dry run trade, 0 for an observation
   int               m_dir[];
   datetime          m_time[];
   int               m_bars[];
   int               m_meta[];      // SMC_META_* structural context at the moment it was booked
   datetime          m_zone[];      // creating candle of the engaged zone: the setup's durable identity
   int               m_budget[];    // bars this observation is allowed, scaled to how far its target is
   int               m_max_bars;    // the budget a median setup gets; others are scaled from it
   CLogger          *m_log;

public:
                     CVirtualBook(void): m_n(0), m_max_bars(120), m_log(NULL) {}

   void              Init(const int features,CLogger *log,const int max_bars=120)
     { m_n=features; m_log=log; m_max_bars=max_bars; }

   int               Count(void) { return(ArraySize(m_dir)); }

   //--- The same setup survives many closes in a row, and booking it once
   //--- per bar lets one market moment dominate the training set.
   //---
   //--- This used to compare entry and stop prices. Entry is the live
   //--- bid/ask, which moves every bar, so the test almost never matched
   //--- and a single structure was booked over and over - measured at up
   //--- to 2.9 stored rows per real setup on live M5 and M15 files. The
   //--- model then trained repeatedly on one market moment, and every
   //--- statistic computed from the file was inflated by the same factor.
   //---
   //--- The zone's creating candle is the durable identity. It survives
   //--- the rebuild that reassigns SZone.uid, and a timestamp compares
   //--- exactly. Entries leave the book when they resolve, so this blocks
   //--- CONCURRENT duplicates only: the same zone may legitimately produce
   //--- a fresh setup later, and that is still recorded.
   bool              Has(const int dir,const double entry,const double sl,const datetime zone_from)
     {
      if(zone_from>0)
        {
         for(int i=ArraySize(m_dir)-1;i>=0;i--)
            if(m_dir[i]==dir && m_zone[i]==zone_from) return(true);
         return(false);
        }
      //--- no zone identity available: fall back to the price comparison
      double tol=MathMax(MathAbs(entry)*1e-6,_Point);
      for(int i=ArraySize(m_dir)-1;i>=0;i--)
         if(m_dir[i]==dir && MathAbs(m_entry[i]-entry)<=tol && MathAbs(m_sl[i]-sl)<=tol)
            return(true);
      return(false);
     }

   void              Add(const double &x[],const double entry,const double sl,const double tp,const int dir,
                         const double lots=0.0,const int meta=0,const datetime zone_from=0)
     {
      if(dir==DIR_NONE || entry<=0.0 || sl<=0.0 || tp<=0.0) return;
      if(MathAbs(entry-sl)<=0.0) return;
      if(Has(dir,entry,sl,zone_from)) return;       // already watching this structure
      if(ArraySize(m_dir)>=VB_MAX) Remove(0);
      int k=ArraySize(m_dir);
      ArrayResize(m_lots,k+1);
      ArrayResize(m_dir,k+1);
      ArrayResize(m_entry,k+1);
      ArrayResize(m_sl,k+1);
      ArrayResize(m_tp,k+1);
      ArrayResize(m_time,k+1);
      ArrayResize(m_bars,k+1);
      ArrayResize(m_meta,k+1);
      ArrayResize(m_zone,k+1);
      ArrayResize(m_budget,k+1);
      ArrayResize(m_x,(k+1)*m_n);
      //--- A far target needs longer to reach, so giving every observation
      //--- the same fixed window is not neutral: it quietly discards the
      //--- distant setups that were slowly WINNING while keeping the ones
      //--- that hit their stop early. That selection manufactures the
      //--- appearance that distant targets fail, and it cannot be measured
      //--- around because the discarded rows are never written down.
      //---
      //--- The budget is therefore proportional to the distance price has
      //--- to travel, anchored so a 1.5R setup keeps exactly the window it
      //--- had before. Clamped either side: a very tight target still gets
      //--- a fair look, and a very distant one cannot occupy a slot forever.
      double rr=SmcSafeDiv(MathAbs(tp-entry),MathAbs(entry-sl),1.5);
      int budget=(int)MathRound(m_max_bars*rr/1.5);
      budget=(int)SmcClamp(budget,m_max_bars/2,m_max_bars*3);
      m_budget[k]=budget;
      m_meta[k]=meta;
      m_zone[k]=zone_from;
      m_dir[k]=dir; m_entry[k]=entry; m_sl[k]=sl; m_tp[k]=tp; m_lots[k]=lots;
      m_time[k]=SmcNow(); m_bars[k]=0;
      for(int i=0;i<m_n;i++) m_x[k*m_n+i]=(i<ArraySize(x)?x[i]:0.0);
     }

   void              Remove(const int i)
     {
      int k=ArraySize(m_dir);
      if(i<0 || i>=k) return;
      ArrayRemove(m_x,i*m_n,m_n);
      ArrayRemove(m_lots,i,1);
      ArrayRemove(m_dir,i,1);
      ArrayRemove(m_entry,i,1);
      ArrayRemove(m_sl,i,1);
      ArrayRemove(m_tp,i,1);
      ArrayRemove(m_time,i,1);
      ArrayRemove(m_bars,i,1);
      ArrayRemove(m_meta,i,1);
      ArrayRemove(m_zone,i,1);
      ArrayRemove(m_budget,i,1);
     }

   //--- resolve every paper setup against the last closed bar ---------
   //--- value_per_price is what one full price unit is worth per 1.00 lot,
   //--- so a dry run trade can be marked to money exactly as a real one is
   //--- cost_price: what a round trip costs, expressed as a price distance.
   //--- A real trade is labelled from realised profit, which is already net
   //--- of spread and commission. An observation was labelled on price alone,
   //--- so the two streams disagreed about what counts as a win by an amount
   //--- that varies from broker to broker - and the model was trained on both.
   //--- Charging the observation the same cost makes the label mean the same
   //--- thing in either stream, and makes the learned model portable.
   int               Resolve(const double bar_high,const double bar_low,COnlineLearner *model,
                             const double value_per_price,double &money_out,
                             const double cost_price=0.0)
     {
      int resolved=0;
      for(int i=ArraySize(m_dir)-1;i>=0;i--)
        {
         m_bars[i]++;
         bool hit_tp=false,hit_sl=false;
         //--- the objective has to clear the round trip to count as a win;
         //--- the stop does not need adjusting, since a costed loss is still
         //--- a loss and the label would not change
         double c=MathMax(cost_price,0.0);
         if(m_dir[i]==DIR_BULL) { hit_sl=(bar_low<=m_sl[i]);  hit_tp=(bar_high>=m_tp[i]+c); }
         else                   { hit_sl=(bar_high>=m_sl[i]); hit_tp=(bar_low <=m_tp[i]-c); }
         double y=-1.0;
         bool   timed_out=false;
         if(hit_sl && hit_tp) y=0.0;                       // ambiguous bar: assume the stop first
         else if(hit_tp) y=1.0;
         else if(hit_sl) y=0.0;
         else if(m_bars[i]>=m_budget[i]) timed_out=true;   // neither side reached in its own window

         //--- A setup that reached neither its objective nor its stop is
         //--- UNRESOLVED, not a failure. Training on it as a loss is what
         //--- collapsed the first live model: 88% of its labels were
         //--- timeouts, the bias saturated negative, and every probability
         //--- fell so low that the expectancy gate demanded 20R+ and
         //--- nothing could ever trade again. Discard it instead.
         if(timed_out)
           {
            if(m_log!=NULL)
               m_log.Debug(StringFormat("Observation discarded unresolved after %d of its %d allowed bars (%.2fR target) - not trained on",
                           m_bars[i],m_budget[i],SmcSafeDiv(MathAbs(m_tp[i]-m_entry[i]),MathAbs(m_entry[i]-m_sl[i]),0.0)));
            Remove(i);
            continue;
           }

         if(y>=0.0)
           {
            double xb[];
            ArrayResize(xb,m_n);
            for(int f=0;f<m_n;f++) xb[f]=m_x[i*m_n+f];
            //--- a dry run trade is a full observation, not a discounted one
            double weight=(m_lots[i]>0.0?1.00:0.60);
            if(model!=NULL) model.Learn(xb,y,weight,m_meta[i]);
            if(m_lots[i]>0.0 && value_per_price>0.0)
              {
               double exit_px=(y>0.5?m_tp[i]:m_sl[i]);
               money_out+=(exit_px-m_entry[i])*m_dir[i]*m_lots[i]*value_per_price;
              }        // paper trades count less than real ones
            if(m_log!=NULL)
               m_log.Debug(StringFormat("Observation resolved [%s]: %s -> %s after %d bars",SmcMetaStr(m_meta[i]),
                           SmcDirShort(m_dir[i]),(y>0.5?"objective":"invalidated"),m_bars[i]));
            Remove(i);
            resolved++;
           }
        }
      return(resolved);
     }
  };

//+------------------------------------------------------------------+
//| Execution wrapper                                                |
//+------------------------------------------------------------------+
class CTradeExec
  {
private:
   CTrade            m_trade;
   string            m_symbol;
   long              m_magic;
   CLogger          *m_log;
   int               m_slippage;

public:
                     CTradeExec(void): m_symbol(""), m_magic(0), m_log(NULL), m_slippage(30) {}

   void              Init(const string symbol,const long magic,const int slippage,CLogger *log)
     {
      m_symbol=symbol; m_magic=magic; m_log=log; m_slippage=slippage;
      m_trade.SetExpertMagicNumber((ulong)magic);
      m_trade.SetDeviationInPoints((ulong)slippage);
      m_trade.SetAsyncMode(false);
      ENUM_SYMBOL_TRADE_EXECUTION exec=(ENUM_SYMBOL_TRADE_EXECUTION)SymbolInfoInteger(symbol,SYMBOL_TRADE_EXEMODE);
      if(exec==SYMBOL_TRADE_EXECUTION_MARKET) m_trade.SetTypeFillingBySymbol(symbol);
      else                                    m_trade.SetTypeFilling(ORDER_FILLING_RETURN);
     }

   CTrade           *Trade(void) { return(GetPointer(m_trade)); }

   //--- broker constraints -------------------------------------------
   double            MinStopDistance(void)
     {
      long lvl=SymbolInfoInteger(m_symbol,SYMBOL_TRADE_STOPS_LEVEL);
      double pt=SymbolInfoDouble(m_symbol,SYMBOL_POINT);
      double frz=(double)SymbolInfoInteger(m_symbol,SYMBOL_TRADE_FREEZE_LEVEL)*pt;
      return(MathMax((double)lvl*pt,frz));
     }

   bool              Open(const int dir,const double lots,const double sl,const double tp,const string comment)
     {
      double price=(dir==DIR_BULL?SymbolInfoDouble(m_symbol,SYMBOL_ASK):SymbolInfoDouble(m_symbol,SYMBOL_BID));
      int    dg=(int)SymbolInfoInteger(m_symbol,SYMBOL_DIGITS);
      double nsl=NormalizeDouble(sl,dg);
      double ntp=NormalizeDouble(tp,dg);
      double stops=MinStopDistance();
      if(stops>0.0)
        {
         //--- The position was sized for THIS stop distance. Widening it here
         //--- to satisfy the broker would quietly increase the real risk
         //--- beyond the budget, and moving the target would change the R:R
         //--- the expectancy gate already approved. Refuse instead - the
         //--- setup will be reconsidered on the next close.
         double sld=(dir==DIR_BULL?price-nsl:nsl-price);
         double tpd=(dir==DIR_BULL?ntp-price:price-ntp);
         if(sld<stops)
           {
            if(m_log!=NULL)
               m_log.Warn(StringFormat("Order refused: the stop is %.5f from price but this broker requires %.5f. Widening it would break the position sizing, so the trade is skipped rather than over-risked.",sld,stops));
            return(false);
           }
         if(tpd<stops)
           {
            if(m_log!=NULL)
               m_log.Warn(StringFormat("Order refused: the target is %.5f from price but this broker requires %.5f.",tpd,stops));
            return(false);
           }
        }
      bool ok=(dir==DIR_BULL?m_trade.Buy(lots,m_symbol,0.0,nsl,ntp,comment)
                            :m_trade.Sell(lots,m_symbol,0.0,nsl,ntp,comment));
      if(!ok && m_log!=NULL)
         m_log.Err(StringFormat("Order rejected: retcode=%d (%s)",m_trade.ResultRetcode(),m_trade.ResultRetcodeDescription()));
      return(ok);
     }

   //--- A stop inside the broker's stops or freeze level is rejected by the
   //--- server, so a break even or trail request that lands there fails
   //--- silently and the position keeps its old stop. Check first, and say
   //--- so, rather than let a risk reduction quietly not happen.
   bool              ModifySl(const ulong ticket,const double sl,const double tp)
     {
      if(!PositionSelectByTicket(ticket)) return(false);
      int    dg=(int)SymbolInfoInteger(m_symbol,SYMBOL_DIGITS);
      double nsl=NormalizeDouble(sl,dg);
      double stops=MinStopDistance();
      long   type=PositionGetInteger(POSITION_TYPE);
      double mkt=(type==POSITION_TYPE_BUY?SymbolInfoDouble(m_symbol,SYMBOL_BID)
                                         :SymbolInfoDouble(m_symbol,SYMBOL_ASK));
      double d=(type==POSITION_TYPE_BUY?mkt-nsl:nsl-mkt);
      if(d<=0.0)
        {
         if(m_log!=NULL)
            m_log.Debug(StringFormat("Stop move to %.5f skipped - price %.5f is already through it",nsl,mkt));
         return(false);
        }
      if(stops>0.0 && d<stops)
        {
         if(m_log!=NULL)
            m_log.Debug(StringFormat("Stop move to %.5f skipped - %.5f from price, broker needs %.5f. Will retry as price advances.",nsl,d,stops));
         return(false);
        }
      if(!m_trade.PositionModify(ticket,nsl,NormalizeDouble(tp,dg)))
        {
         if(m_log!=NULL)
            m_log.Warn(StringFormat("Stop move to %.5f rejected: %d %s",nsl,
                       m_trade.ResultRetcode(),m_trade.ResultRetcodeDescription()));
         return(false);
        }
      return(true);
     }

   bool              PartialClose(const ulong ticket,const double volume)
     {
      double step=SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_STEP);
      double vmin=SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_MIN);
      if(step<=0.0) step=0.01;
      int vd=0; double t=step;
      while(t<1.0-1e-9 && vd<8) { t*=10.0; vd++; }
      double v=MathFloor(volume/step+1e-9)*step;
      v=NormalizeDouble(v,vd);
      if(v<vmin) return(false);
      //--- never close so much that the remainder falls below the minimum
      double remain=NormalizeDouble(PositionGetDouble(POSITION_VOLUME)-v,vd);
      if(remain>0.0 && remain<vmin) return(false);
      return(m_trade.PositionClosePartial(ticket,v));
     }

   bool              Close(const ulong ticket) { return(m_trade.PositionClose(ticket)); }

   int               CloseAll(const string reason)
     {
      int closed=0;
      for(int i=PositionsTotal()-1;i>=0;i--)
        {
         ulong t=PositionGetTicket(i);
         if(t==0) continue;
         if(PositionGetString(POSITION_SYMBOL)!=m_symbol) continue;
         if(PositionGetInteger(POSITION_MAGIC)!=m_magic) continue;
         if(m_trade.PositionClose(t)) closed++;
        }
      if(closed>0 && m_log!=NULL) m_log.Warn(StringFormat("Flattened %d position(s): %s",closed,reason));
      return(closed);
     }

   int               OpenCount(void)
     {
      int c=0;
      for(int i=PositionsTotal()-1;i>=0;i--)
        {
         ulong t=PositionGetTicket(i);
         if(t==0) continue;
         if(PositionGetString(POSITION_SYMBOL)!=m_symbol) continue;
         if(PositionGetInteger(POSITION_MAGIC)!=m_magic) continue;
         c++;
        }
      return(c);
     }

   //--- Realised result of a closed position.
   //--- Returns false until the closing deal is actually present in the
   //--- terminal's history. The caller must NOT invent a label from a
   //--- false return: a deal that has not been written yet is not a loss.
   bool              ClosedResult(const ulong position_id,double &profit)
     {
      profit=0.0;
      if(!HistorySelectByPosition(position_id)) return(false);
      int deals=HistoryDealsTotal();
      bool has_exit=false;
      double sum=0.0;
      for(int i=0;i<deals;i++)
        {
         ulong d=HistoryDealGetTicket(i);
         if(d==0) continue;
         long entry_type=HistoryDealGetInteger(d,DEAL_ENTRY);
         if(entry_type==DEAL_ENTRY_OUT || entry_type==DEAL_ENTRY_OUT_BY || entry_type==DEAL_ENTRY_INOUT)
            has_exit=true;
         sum+=HistoryDealGetDouble(d,DEAL_PROFIT)
             +HistoryDealGetDouble(d,DEAL_SWAP)
             +HistoryDealGetDouble(d,DEAL_COMMISSION);
        }
      if(!has_exit) return(false);          // still settling
      profit=sum;
      return(true);
     }
  };

#endif // __SMC_TRADEMANAGER_MQH__
