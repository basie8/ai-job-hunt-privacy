//+------------------------------------------------------------------+
//|                                                  MarketState.mqh |
//|                                                                  |
//|  Live read of the chart. Everything the agent later uses as a     |
//|  "threshold" is calibrated here from the visible distribution of  |
//|  candles, so no fixed technical parameter is ever hard-coded into |
//|  a trading decision.                                              |
//+------------------------------------------------------------------+
#ifndef __SMC_MARKETSTATE_MQH__
#define __SMC_MARKETSTATE_MQH__

#include "Defs.mqh"
#include "TimeZones.mqh"

#define SMC_CAL_BARS   400   // size of the observation window used for calibration
#define SMC_HIST_BARS  1200  // how much history is pulled for structure mapping

class CMarketState
  {
private:
   string            m_symbol;
   ENUM_TIMEFRAMES   m_tf_entry;
   ENUM_TIMEFRAMES   m_tf_mid;
   ENUM_TIMEFRAMES   m_tf_high;

   MqlRates          m_r_entry[];
   MqlRates          m_r_mid[];
   MqlRates          m_r_high[];

   //--- calibration output (all measured, none configured) ----------
   double            m_tr_med;
   double            m_tr_p20;
   double            m_tr_p80;
   double            m_tr_p95;
   double            m_body_med;
   double            m_body_p80;
   double            m_range_recent;   // median TR of the last 20 bars
   double            m_vol_regime;     // recent TR / long TR  (1.0 = normal)
   double            m_gap_p70;        // 70th pct of non-zero 3-bar imbalances
   double            m_tick_vol_med;
   int               m_pivot_len;      // adaptive swing sensitivity
   double            m_point;
   int               m_digits;

   void              PickHigherTimeframes(void)
     {
      switch(m_tf_entry)
        {
         case PERIOD_M1:  m_tf_mid=PERIOD_M15; m_tf_high=PERIOD_H1;  break;
         case PERIOD_M2:
         case PERIOD_M3:
         case PERIOD_M4:
         case PERIOD_M5:  m_tf_mid=PERIOD_M30; m_tf_high=PERIOD_H4;  break;
         case PERIOD_M6:
         case PERIOD_M10:
         case PERIOD_M12:
         case PERIOD_M15: m_tf_mid=PERIOD_H1;  m_tf_high=PERIOD_H4;  break;
         case PERIOD_M20:
         case PERIOD_M30: m_tf_mid=PERIOD_H4;  m_tf_high=PERIOD_D1;  break;
         case PERIOD_H1:  m_tf_mid=PERIOD_H4;  m_tf_high=PERIOD_D1;  break;
         case PERIOD_H2:
         case PERIOD_H3:
         case PERIOD_H4:  m_tf_mid=PERIOD_D1;  m_tf_high=PERIOD_W1;  break;
         default:         m_tf_mid=PERIOD_D1;  m_tf_high=PERIOD_W1;  break;
        }
     }

   //--- true range series of the calibration window ------------------
   void              BuildStats(void)
     {
      int n=ArraySize(m_r_entry);
      if(n<30) return;
      int win=(int)MathMin(SMC_CAL_BARS,n-1);

      double tr[],body[],vol[],gaps[];
      ArrayResize(tr,win);
      ArrayResize(body,win);
      ArrayResize(vol,win);
      int gcnt=0;
      ArrayResize(gaps,win);

      for(int i=0;i<win;i++)
        {
         double h=m_r_entry[i].high,l=m_r_entry[i].low,pc=m_r_entry[i+1].close;
         double t=MathMax(h-l,MathMax(MathAbs(h-pc),MathAbs(l-pc)));
         tr[i]=t;
         body[i]=MathAbs(m_r_entry[i].close-m_r_entry[i].open);
         vol[i]=(double)m_r_entry[i].tick_volume;
        }
      //--- 3 candle imbalances inside the window
      for(int i=1;i<win-1;i++)
        {
         double up=m_r_entry[i-1].low-m_r_entry[i+1].high;   // bullish gap
         double dn=m_r_entry[i+1].low-m_r_entry[i-1].high;   // bearish gap
         double g=MathMax(up,dn);
         if(g>0.0) { gaps[gcnt]=g; gcnt++; }
        }
      ArrayResize(gaps,MathMax(gcnt,1));
      if(gcnt==0) gaps[0]=0.0;

      m_tr_med  = SmcPercentile(tr,0.50);
      m_tr_p20  = SmcPercentile(tr,0.20);
      m_tr_p80  = SmcPercentile(tr,0.80);
      m_tr_p95  = SmcPercentile(tr,0.95);
      m_body_med= SmcPercentile(body,0.50);
      m_body_p80= SmcPercentile(body,0.80);
      m_gap_p70 = (gcnt>3?SmcPercentile(gaps,0.70):m_tr_med*0.35);
      m_tick_vol_med=SmcPercentile(vol,0.50);

      //--- short window volatility to detect expansion / dead tape
      int sw=(int)MathMin(20,win);
      double trs[];
      ArrayResize(trs,sw);
      for(int i=0;i<sw;i++) trs[i]=tr[i];
      m_range_recent=SmcPercentile(trs,0.50);
      m_vol_regime=SmcSafeDiv(m_range_recent,m_tr_med,1.0);

      CalibratePivot(win);
     }

   //--- choose the swing sensitivity that matches the market's own
   //--- rhythm: we target ~1 confirmed pivot every 7-9 candles.
   void              CalibratePivot(const int win)
     {
      int    best=3;
      double best_err=1e9;
      for(int L=2;L<=6;L++)
        {
         int cnt=0;
         for(int i=L;i<win-L;i++)
           {
            bool sh=true,sl=true;
            for(int k=1;k<=L;k++)
              {
               if(m_r_entry[i].high<=m_r_entry[i-k].high || m_r_entry[i].high<m_r_entry[i+k].high) sh=false;
               if(m_r_entry[i].low >=m_r_entry[i-k].low  || m_r_entry[i].low >m_r_entry[i+k].low ) sl=false;
               if(!sh && !sl) break;
              }
            if(sh || sl) cnt++;
           }
         double density=SmcSafeDiv((double)cnt,(double)(win-2*L),0.0);
         double err=MathAbs(density-0.125);   // one pivot every ~8 bars
         if(err<best_err) { best_err=err; best=L; }
        }
      m_pivot_len=best;
     }

public:
                     CMarketState(void): m_symbol(""), m_tf_entry(PERIOD_CURRENT), m_tf_mid(PERIOD_H1),
                                         m_tf_high(PERIOD_H4), m_tr_med(0), m_tr_p20(0), m_tr_p80(0), m_tr_p95(0),
                                         m_body_med(0), m_body_p80(0), m_range_recent(0), m_vol_regime(1.0),
                                         m_gap_p70(0), m_tick_vol_med(0), m_pivot_len(3), m_point(0), m_digits(2) {}

   bool              Init(const string symbol,const ENUM_TIMEFRAMES tf)
     {
      m_symbol=symbol;
      m_tf_entry=(tf==PERIOD_CURRENT?(ENUM_TIMEFRAMES)Period():tf);
      PickHigherTimeframes();
      m_point =SymbolInfoDouble(m_symbol,SYMBOL_POINT);
      m_digits=(int)SymbolInfoInteger(m_symbol,SYMBOL_DIGITS);
      ArraySetAsSeries(m_r_entry,true);
      ArraySetAsSeries(m_r_mid,true);
      ArraySetAsSeries(m_r_high,true);
      return(Refresh());
     }

   bool              Refresh(void)
     {
      int c1=CopyRates(m_symbol,m_tf_entry,0,SMC_HIST_BARS,m_r_entry);
      int c2=CopyRates(m_symbol,m_tf_mid,0,600,m_r_mid);
      int c3=CopyRates(m_symbol,m_tf_high,0,400,m_r_high);
      if(c1<60 || c2<30 || c3<20) return(false);
      ArraySetAsSeries(m_r_entry,true);
      ArraySetAsSeries(m_r_mid,true);
      ArraySetAsSeries(m_r_high,true);
      BuildStats();
      return(true);
     }

   //--- accessors ---------------------------------------------------
   string            Symbol(void) const { return(m_symbol); }
   ENUM_TIMEFRAMES   TfEntry(void) const { return(m_tf_entry); }
   ENUM_TIMEFRAMES   TfMid(void)   const { return(m_tf_mid);   }
   ENUM_TIMEFRAMES   TfHigh(void)  const { return(m_tf_high);  }
   int               Digits_(void) const { return(m_digits); }
   double            Point_(void)  const { return(m_point);  }

   int               BarsEntry(void) { return(ArraySize(m_r_entry)); }
   int               BarsMid(void)   { return(ArraySize(m_r_mid));   }
   int               BarsHigh(void)  { return(ArraySize(m_r_high));  }

   //--- explicit element wise copy: dst[0] is always the newest bar
   void              CopyEntry(MqlRates &dst[])
     {
      int n=ArraySize(m_r_entry);
      ArrayResize(dst,n);
      for(int i=0;i<n;i++) dst[i]=m_r_entry[i];
     }
   void              CopyMid(MqlRates &dst[])
     {
      int n=ArraySize(m_r_mid);
      ArrayResize(dst,n);
      for(int i=0;i<n;i++) dst[i]=m_r_mid[i];
     }
   void              CopyHigh(MqlRates &dst[])
     {
      int n=ArraySize(m_r_high);
      ArrayResize(dst,n);
      for(int i=0;i<n;i++) dst[i]=m_r_high[i];
     }

   //--- direct indexed access (0 = current forming bar) --------------
   double            EHigh(const int i)  { return(i>=0 && i<ArraySize(m_r_entry)?m_r_entry[i].high :0.0); }
   double            ELow(const int i)   { return(i>=0 && i<ArraySize(m_r_entry)?m_r_entry[i].low  :0.0); }
   double            EOpen(const int i)  { return(i>=0 && i<ArraySize(m_r_entry)?m_r_entry[i].open :0.0); }
   double            EClose(const int i) { return(i>=0 && i<ArraySize(m_r_entry)?m_r_entry[i].close:0.0); }
   datetime          ETime(const int i)  { return(i>=0 && i<ArraySize(m_r_entry)?m_r_entry[i].time :0);   }
   long              EVol(const int i)   { return(i>=0 && i<ArraySize(m_r_entry)?(long)m_r_entry[i].tick_volume:0); }

   //--- calibration output ------------------------------------------
   double            TrMed(void)   const { return(m_tr_med);   }
   double            TrP20(void)   const { return(m_tr_p20);   }
   double            TrP80(void)   const { return(m_tr_p80);   }
   double            TrP95(void)   const { return(m_tr_p95);   }
   double            BodyMed(void) const { return(m_body_med); }
   double            BodyP80(void) const { return(m_body_p80); }
   double            GapP70(void)  const { return(m_gap_p70);  }
   double            VolRegime(void) const { return(m_vol_regime); }
   double            TickVolMed(void) const { return(m_tick_vol_med); }
   int               PivotLen(void) const { return(m_pivot_len); }

   //--- unit of "one normal candle" used everywhere as a scale -------
   double            Unit(void) const { return(m_tr_med>0.0?m_tr_med:1.0); }

   //--- current spread in price and in local units -------------------
   double            SpreadPrice(void)
     {
      double a=SymbolInfoDouble(m_symbol,SYMBOL_ASK);
      double b=SymbolInfoDouble(m_symbol,SYMBOL_BID);
      return(MathMax(a-b,0.0));
     }
   double            SpreadUnits(void) { return(SmcSafeDiv(SpreadPrice(),Unit(),0.0)); }

   //--- true range of a given entry-TF bar --------------------------
   double            TrueRange(const int i)
     {
      if(i<0 || i+1>=ArraySize(m_r_entry)) return(0.0);
      double h=m_r_entry[i].high,l=m_r_entry[i].low,pc=m_r_entry[i+1].close;
      return(MathMax(h-l,MathMax(MathAbs(h-pc),MathAbs(l-pc))));
     }

   //--- daily / weekly reference levels ------------------------------
   bool              PrevDayLevels(double &hi,double &lo)
     {
      MqlRates d[];
      ArraySetAsSeries(d,true);
      if(CopyRates(m_symbol,PERIOD_D1,0,3,d)<2) return(false);
      hi=d[1].high; lo=d[1].low;
      return(true);
     }
   bool              PrevWeekLevels(double &hi,double &lo)
     {
      MqlRates w[];
      ArraySetAsSeries(w,true);
      if(CopyRates(m_symbol,PERIOD_W1,0,3,w)<2) return(false);
      hi=w[1].high; lo=w[1].low;
      return(true);
     }

   //--- Accumulation ("asian") range: the hours before London opens.
   //--- Anchored to London local 00:00-07:00 rather than to fixed GMT,
   //--- so it keeps its meaning across a daylight saving change.
   bool              AsianRange(const int gmt_offset,double &hi,double &lo)
     {
      MqlRates m[];
      ArraySetAsSeries(m,true);
      int cnt=CopyRates(m_symbol,PERIOD_M15,0,400,m);
      if(cnt<20) return(false);
      datetime now_utc=SmcServerToUtc(SmcNow(),gmt_offset);
      datetime today_local=SmcZoneDayStart(TZ_LONDON,now_utc);
      hi=-DBL_MAX; lo=DBL_MAX;
      for(int i=0;i<cnt;i++)
        {
         datetime b_utc=SmcServerToUtc(m[i].time,gmt_offset);
         datetime b_loc=SmcUtcToZone(TZ_LONDON,b_utc);
         datetime b_day=SmcDayStart(b_loc);
         if(b_day>today_local) continue;               // future session, ignore
         if(b_day<today_local) break;                  // walked past today's accumulation
         MqlDateTime dt;
         TimeToStruct(b_loc,dt);
         double lh=dt.hour+dt.min/60.0;
         if(lh>=0.0 && lh<7.0)
           {
            hi=MathMax(hi,m[i].high);
            lo=MathMin(lo,m[i].low);
           }
        }
      if(hi<=-DBL_MAX*0.5 || lo>=DBL_MAX*0.5) return(false);
      return(true);
     }
  };

#endif // __SMC_MARKETSTATE_MQH__
