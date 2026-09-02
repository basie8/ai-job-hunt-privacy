//+------------------------------------------------------------------+
//|                                                  RiskManager.mqh |
//|                                                                  |
//|  FTMO 2-step compliant capital protection.                       |
//|                                                                  |
//|  Hard objectives implemented here (2-step programme):            |
//|    Phase 1 (Challenge)     : +10% target                         |
//|    Phase 2 (Verification)  : +5%  target                         |
//|    Maximum daily loss      : 5% of the initial capital,          |
//|                              measured against the balance at the |
//|                              daily reset (midnight CE(S)T) and   |
//|                              including floating P/L              |
//|    Maximum overall loss    : 10% of the initial capital (static) |
//|    Minimum trading days    : 4 per phase                         |
//|                                                                  |
//|  The agent never trades up to the limit. It works inside a       |
//|  layered envelope: a soft stop that ends the trading day, a      |
//|  hard floor that flattens everything, and a per-trade budget     |
//|  that can never, even in the worst case fill, reach the floor.   |
//+------------------------------------------------------------------+
#ifndef __SMC_RISKMANAGER_MQH__
#define __SMC_RISKMANAGER_MQH__

#include "Defs.mqh"
#include "Logger.mqh"

class CRiskManager
  {
private:
   string            m_symbol;
   long              m_magic;
   CLogger          *m_log;

   double            m_initial;          // initial simulated capital of the phase
   int               m_phase;            // 1 or 2
   double            m_target_pct;       // phase profit target
   double            m_daily_pct;        // 5.0
   double            m_max_pct;          // 10.0
   double            m_soft_daily_pct;   // where the agent stops for the day
   double            m_hard_daily_pct;   // where the agent flattens everything
   double            m_soft_max_pct;
   double            m_base_risk_pct;    // per trade, of the initial capital
   int               m_reset_hour;       // server hour of the FTMO daily reset
   int               m_min_days;

   double            m_day_ref;          // reference balance/equity of the trading day
   datetime          m_day_start;
   double            m_day_low_equity;
   double            m_day_realised;
   int               m_day_trades;
   bool              m_day_locked;
   string            m_lock_reason;

   int               m_loss_streak;
   int               m_win_streak;
   int               m_trading_days;
   datetime          m_last_trade_day;
   int               m_week_trades;
   datetime          m_week_start;

   double            m_peak_equity;
   string            m_state_file;

   double            Bal(void)  { return(AccountInfoDouble(ACCOUNT_BALANCE)); }
   double            Eq(void)   { return(AccountInfoDouble(ACCOUNT_EQUITY));  }

   datetime          ResetAnchor(const datetime now)
     {
      datetime d=SmcDayStart(now)+(datetime)(m_reset_hour*3600);
      if(now<d) d-=(datetime)86400;
      return(d);
     }

public:
                     CRiskManager(void): m_symbol(""), m_magic(0), m_log(NULL), m_initial(0), m_phase(1),
                                         m_target_pct(10.0), m_daily_pct(5.0), m_max_pct(10.0),
                                         m_soft_daily_pct(2.5), m_hard_daily_pct(3.5), m_soft_max_pct(7.0),
                                         m_base_risk_pct(0.5), m_reset_hour(0), m_min_days(4),
                                         m_day_ref(0), m_day_start(0), m_day_low_equity(0), m_day_realised(0),
                                         m_day_trades(0), m_day_locked(false), m_lock_reason(""),
                                         m_loss_streak(0), m_win_streak(0), m_trading_days(0), m_last_trade_day(0),
                                         m_week_trades(0), m_week_start(0), m_peak_equity(0),
                                         m_state_file("smc_agent_state.csv") {}

   void              Init(const string symbol,const long magic,CLogger *log,const double initial_capital,
                          const int phase,const double target_pct,const double daily_pct,const double max_pct,
                          const double soft_daily_pct,const double hard_daily_pct,const double soft_max_pct,
                          const double base_risk_pct,const int reset_hour,const int min_days,
                          const string state_file)
     {
      m_symbol=symbol; m_magic=magic; m_log=log;
      m_phase=phase;
      m_target_pct=target_pct;
      m_daily_pct=daily_pct;
      m_max_pct=max_pct;
      m_soft_daily_pct=MathMin(soft_daily_pct,daily_pct*0.7);
      m_hard_daily_pct=MathMin(hard_daily_pct,daily_pct*0.8);
      m_soft_max_pct=MathMin(soft_max_pct,max_pct*0.8);
      m_base_risk_pct=base_risk_pct;
      m_reset_hour=reset_hour;
      m_min_days=min_days;
      m_state_file=state_file;
      m_initial=(initial_capital>0.0?initial_capital:Bal());
      m_peak_equity=Eq();
      LoadState();
      NewDayCheck(true);
     }

   //--- daily / weekly rollover ---------------------------------------
   void              NewDayCheck(const bool force=false)
     {
      datetime now=SmcNow();
      datetime anchor=ResetAnchor(now);
      if(force || anchor!=m_day_start)
        {
         m_day_start=anchor;
         //--- conservative reference: the worse of balance and equity
         m_day_ref=MathMin(Bal(),Eq());
         m_day_low_equity=Eq();
         m_day_realised=0.0;
         m_day_trades=0;
         m_day_locked=false;
         m_lock_reason="";
         if(m_log!=NULL)
            m_log.Info(StringFormat("New trading day. Reference=%.2f  daily floor=%.2f  overall floor=%.2f",
                       m_day_ref,DailyFloor(),OverallFloor()));
        }
      datetime ws=SmcWeekStart(now);
      if(ws!=m_week_start) { m_week_start=ws; m_week_trades=0; }
      double e=Eq();
      if(e<m_day_low_equity) m_day_low_equity=e;
      if(e>m_peak_equity)    m_peak_equity=e;
     }

   //--- absolute limits ------------------------------------------------
   double            DailyFloor(void)    { return(m_day_ref-m_initial*m_daily_pct/100.0); }
   double            OverallFloor(void)  { return(m_initial-m_initial*m_max_pct/100.0);   }
   double            SoftDailyFloor(void){ return(m_day_ref-m_initial*m_soft_daily_pct/100.0); }
   double            HardDailyFloor(void){ return(m_day_ref-m_initial*m_hard_daily_pct/100.0); }
   double            SoftMaxFloor(void)  { return(m_initial-m_initial*m_soft_max_pct/100.0);   }
   double            TargetEquity(void)  { return(m_initial+m_initial*m_target_pct/100.0);     }

   //--- current state --------------------------------------------------
   double            Initial(void)  const { return(m_initial); }
   int               Phase(void)    const { return(m_phase);   }
   double            DayRef(void)   const { return(m_day_ref); }
   double            DayPnL(void)   { return(Eq()-m_day_ref); }
   double            DayPnLPct(void){ return(SmcSafeDiv(DayPnL(),m_initial,0.0)*100.0); }
   double            TotalPnLPct(void) { return(SmcSafeDiv(Eq()-m_initial,m_initial,0.0)*100.0); }
   double            TargetProgress(void) { return(SmcClamp(SmcSafeDiv(Eq()-m_initial,m_initial*m_target_pct/100.0,0.0),0.0,2.0)); }
   int               DayTrades(void)const { return(m_day_trades); }
   int               WeekTrades(void)const{ return(m_week_trades); }
   int               TradingDays(void)const{ return(m_trading_days); }
   int               MinDays(void)  const { return(m_min_days); }
   int               LossStreak(void)const{ return(m_loss_streak); }
   bool              DayLocked(void)const { return(m_day_locked); }
   string            LockReason(void)const{ return(m_lock_reason); }
   double            RemainingDailyBudget(void) { return(MathMax(Eq()-SoftDailyFloor(),0.0)); }
   double            RemainingHardBudget(void)  { return(MathMax(Eq()-MathMax(HardDailyFloor(),OverallFloor()),0.0)); }

   void              Lock(const string reason)
     {
      if(!m_day_locked && m_log!=NULL) m_log.Warn("Trading locked for the day: "+reason);
      m_day_locked=true;
      m_lock_reason=reason;
     }

   //--- must every open position be flattened right now? ---------------
   bool              MustFlatten(string &reason)
     {
      double e=Eq();
      if(e<=HardDailyFloor())
        { reason=StringFormat("equity %.2f hit the hard daily floor %.2f",e,HardDailyFloor()); return(true); }
      if(e<=SoftMaxFloor())
        { reason=StringFormat("equity %.2f hit the protective overall floor %.2f",e,SoftMaxFloor()); return(true); }
      reason="";
      return(false);
     }

   //--- may the agent open a new position? -----------------------------
   bool              CanOpen(string &reason)
     {
      NewDayCheck();
      if(m_day_locked) { reason="day locked: "+m_lock_reason; return(false); }
      double e=Eq();
      if(e<=SoftDailyFloor())
        { Lock(StringFormat("soft daily stop reached (%.2f%%)",m_soft_daily_pct)); reason="soft daily stop"; return(false); }
      if(e<=SoftMaxFloor())
        { Lock("protective overall drawdown reached"); reason="overall drawdown guard"; return(false); }
      if(e>=TargetEquity() && m_trading_days>=m_min_days)
        { reason=StringFormat("phase %d target reached (%.2f%%) - capital preservation mode",m_phase,m_target_pct); return(false); }
      if(RemainingDailyBudget()<=m_initial*0.0015)
        { reason="remaining daily budget too small for a compliant stop distance"; return(false); }
      reason="";
      return(true);
     }

   //--- money that may be risked on the next trade ----------------------
   double            RiskMoney(const double confidence)
     {
      double risk=m_initial*m_base_risk_pct/100.0;

      //--- conviction scaling: 0.5x at the acceptance threshold, 1.35x at p=0.85
      double conv=SmcClamp(0.5+(confidence-0.55)*2.8,0.45,1.35);
      risk*=conv;

      //--- de-risk after losses, never martingale
      if(m_loss_streak==1) risk*=0.75;
      if(m_loss_streak==2) risk*=0.55;
      if(m_loss_streak>=3) risk*=0.40;

      //--- protect a nearly completed phase
      double prog=TargetProgress();
      if(prog>=0.70) risk*=0.65;
      if(prog>=0.90) risk*=0.45;

      //--- never risk more than a third of what is left before the soft stop,
      //--- and never more than a fifth of what is left before the hard floor
      double cap1=RemainingDailyBudget()/3.0;
      double cap2=RemainingHardBudget()/5.0;
      risk=MathMin(risk,MathMin(cap1,cap2));
      return(MathMax(risk,0.0));
     }

   //--- lot size for a given money risk and stop distance ---------------
   double            Lots(const double risk_money,const double sl_distance)
     {
      if(sl_distance<=0.0 || risk_money<=0.0) return(0.0);
      double tick_val=SymbolInfoDouble(m_symbol,SYMBOL_TRADE_TICK_VALUE);
      double tick_sz =SymbolInfoDouble(m_symbol,SYMBOL_TRADE_TICK_SIZE);
      if(tick_sz<=0.0 || tick_val<=0.0) return(0.0);
      double loss_per_lot=(sl_distance/tick_sz)*tick_val;
      if(loss_per_lot<=0.0) return(0.0);
      double lots=risk_money/loss_per_lot;

      double vmin=SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_MIN);
      double vmax=SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_MAX);
      double vstep=SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_STEP);
      if(vstep<=0.0) vstep=0.01;
      lots=MathFloor(lots/vstep)*vstep;
      lots=NormalizeDouble(lots,2);
      if(lots<vmin) return(0.0);           // cannot size compliantly -> skip the trade
      if(lots>vmax) lots=vmax;

      //--- margin sanity check
      double margin=0.0;
      double price=SymbolInfoDouble(m_symbol,SYMBOL_ASK);
      if(OrderCalcMargin(ORDER_TYPE_BUY,m_symbol,lots,price,margin))
        {
         double free_margin=AccountInfoDouble(ACCOUNT_MARGIN_FREE);
         while(lots>=vmin && margin>free_margin*0.35)
           {
            lots=NormalizeDouble(lots-vstep,2);
            if(lots<vmin) return(0.0);
            if(!OrderCalcMargin(ORDER_TYPE_BUY,m_symbol,lots,price,margin)) break;
           }
        }
      return(lots);
     }

   //--- worst case check before sending an order -------------------------
   bool              WorstCaseAcceptable(const double lots,const double sl_distance,string &reason)
     {
      double tick_val=SymbolInfoDouble(m_symbol,SYMBOL_TRADE_TICK_VALUE);
      double tick_sz =SymbolInfoDouble(m_symbol,SYMBOL_TRADE_TICK_SIZE);
      if(tick_sz<=0.0) { reason="symbol tick size unavailable"; return(false); }
      //--- assume a 25% slippage/gap overshoot beyond the stop
      double worst=(sl_distance*1.25/tick_sz)*tick_val*lots;
      double open_risk=OpenRiskMoney();
      if(Eq()-(worst+open_risk)<=HardDailyFloor())
        { reason=StringFormat("worst case %.2f + open risk %.2f would breach the hard daily floor",worst,open_risk); return(false); }
      if(Eq()-(worst+open_risk)<=SoftMaxFloor())
        { reason="worst case would breach the protective overall floor"; return(false); }
      reason="";
      return(true);
     }

   //--- money currently at risk in open positions of this EA --------------
   double            OpenRiskMoney(void)
     {
      double total=0.0;
      double tick_val=SymbolInfoDouble(m_symbol,SYMBOL_TRADE_TICK_VALUE);
      double tick_sz =SymbolInfoDouble(m_symbol,SYMBOL_TRADE_TICK_SIZE);
      if(tick_sz<=0.0) return(0.0);
      for(int i=PositionsTotal()-1;i>=0;i--)
        {
         ulong ticket=PositionGetTicket(i);
         if(ticket==0) continue;
         if(PositionGetString(POSITION_SYMBOL)!=m_symbol) continue;
         if(PositionGetInteger(POSITION_MAGIC)!=m_magic) continue;
         double sl=PositionGetDouble(POSITION_SL);
         double price=PositionGetDouble(POSITION_PRICE_CURRENT);
         double vol=PositionGetDouble(POSITION_VOLUME);
         if(sl<=0.0) { total+=vol*(price/tick_sz)*tick_val*0.02; continue; }   // no stop: assume 2%
         double dist=MathAbs(price-sl);
         total+=(dist/tick_sz)*tick_val*vol;
        }
      return(total);
     }

   //--- bookkeeping -------------------------------------------------------
   void              OnTradeOpened(void)
     {
      m_day_trades++;
      m_week_trades++;
      datetime d=SmcDayStart(SmcNow());
      if(d!=m_last_trade_day) { m_last_trade_day=d; m_trading_days++; SaveState(); }
     }

   void              OnTradeClosed(const double profit)
     {
      m_day_realised+=profit;
      if(profit<0.0) { m_loss_streak++; m_win_streak=0; }
      else if(profit>0.0) { m_win_streak++; m_loss_streak=0; }
      if(m_log!=NULL)
         m_log.Info(StringFormat("Trade closed P/L=%.2f  day=%.2f%%  total=%.2f%%  streak L%d/W%d",
                    profit,DayPnLPct(),TotalPnLPct(),m_loss_streak,m_win_streak));
      SaveState();
     }

   //--- persistence --------------------------------------------------------
   bool              SaveState(void)
     {
      int h=FileOpen(m_state_file,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
      if(h==INVALID_HANDLE) return(false);
      FileWrite(h,"SMC_AGENT_STATE",DoubleToString(m_initial,2),(string)m_trading_days,
                (string)(long)m_last_trade_day,(string)m_loss_streak,(string)m_win_streak,
                DoubleToString(m_peak_equity,2));
      FileClose(h);
      return(true);
     }

   bool              LoadState(void)
     {
      int h=FileOpen(m_state_file,FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
      if(h==INVALID_HANDLE) return(false);
      bool ok=false;
      while(!FileIsEnding(h))
        {
         string line=FileReadString(h);
         string p[];
         int k=StringSplit(line,'\t',p);
         if(k<2) k=StringSplit(line,';',p);
         if(k>=7 && p[0]=="SMC_AGENT_STATE")
           {
            double init=StringToDouble(p[1]);
            if(init>0.0 && MathAbs(init-m_initial)/MathMax(init,1.0)<0.5) m_initial=init;
            m_trading_days=(int)StringToInteger(p[2]);
            m_last_trade_day=(datetime)StringToInteger(p[3]);
            m_loss_streak=(int)StringToInteger(p[4]);
            m_win_streak=(int)StringToInteger(p[5]);
            m_peak_equity=StringToDouble(p[6]);
            ok=true;
           }
        }
      FileClose(h);
      return(ok);
     }
  };

#endif // __SMC_RISKMANAGER_MQH__
