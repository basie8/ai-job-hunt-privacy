//+------------------------------------------------------------------+
//|                                                    SmcEngine.mqh |
//|                                                                  |
//|  Pure price-action reader. Rebuilds, on every closed bar, the     |
//|  same picture a LuxAlgo "Smart Money Concepts" chart shows:       |
//|    - swing + internal market structure (BOS / CHoCH)              |
//|    - swing and internal order blocks                              |
//|    - fair value gaps (imbalances)                                 |
//|    - equal highs / equal lows and other liquidity pools           |
//|    - liquidity sweeps (stop raids)                                |
//|    - the dealing range with premium / equilibrium / discount      |
//|                                                                  |
//|  It uses no indicator and no fixed parameter: candle geometry     |
//|  and the distribution of the visible candles decide everything.   |
//+------------------------------------------------------------------+
#ifndef __SMC_ENGINE_MQH__
#define __SMC_ENGINE_MQH__

#include "Defs.mqh"

#define SMC_MAX_SWINGS   80
#define SMC_MAX_ZONES    60
#define SMC_MAX_EVENTS   40
#define SMC_MAX_LIQ      40

class CSmcEngine
  {
private:
   string            m_label;
   MqlRates          m_r[];
   int               m_bars;

   //--- self calibration -------------------------------------------
   double            m_unit;        // median true range of this timeframe
   double            m_gap_thr;     // significant imbalance size
   double            m_vol_med;     // median tick volume
   int               m_pivot;       // swing sensitivity (adaptive)
   int               m_ipivot;      // internal structure sensitivity

   //--- results ----------------------------------------------------
   SSwing            m_swings[];
   SZone             m_zones[];
   SStructEvent      m_events[];
   SLiquidity        m_liq[];

   int               m_trend;       // swing structure trend
   int               m_itrend;      // internal structure trend
   datetime          m_last_choch;
   int               m_last_choch_dir;
   datetime          m_last_bos;
   int               m_last_bos_dir;

   double            m_range_hi;
   double            m_range_lo;
   datetime          m_range_hi_t;
   datetime          m_range_lo_t;

   //--- last detected liquidity sweep -------------------------------
   bool              m_sweep_valid;
   int               m_sweep_reaction_dir;  // direction expected after the raid
   double            m_sweep_price;
   double            m_sweep_extreme;
   datetime          m_sweep_time;
   int               m_sweep_age;           // bars since the sweep
   double            m_sweep_quality;       // 0..1
   string            m_sweep_pool;

   long              m_uid;

   //--- helpers -----------------------------------------------------
   double            H(const int i) { return(m_r[i].high);  }
   double            L(const int i) { return(m_r[i].low);   }
   double            O(const int i) { return(m_r[i].open);  }
   double            C(const int i) { return(m_r[i].close); }
   datetime          T(const int i) { return(m_r[i].time);  }

   bool              IsPivotHigh(const int p,const int len)
     {
      if(p-len<0 || p+len>=m_bars) return(false);
      for(int k=1;k<=len;k++)
        {
         if(m_r[p].high<=m_r[p-k].high) return(false);   // newer side: strictly higher
         if(m_r[p].high< m_r[p+k].high) return(false);   // older side
        }
      return(true);
     }

   bool              IsPivotLow(const int p,const int len)
     {
      if(p-len<0 || p+len>=m_bars) return(false);
      for(int k=1;k<=len;k++)
        {
         if(m_r[p].low>=m_r[p-k].low) return(false);
         if(m_r[p].low> m_r[p+k].low) return(false);
        }
      return(true);
     }

   void              Calibrate(void)
     {
      int win=(int)MathMin(400,m_bars-1);
      if(win<30) { m_unit=0.0; return; }
      double tr[],vol[],gaps[];
      ArrayResize(tr,win); ArrayResize(vol,win); ArrayResize(gaps,win);
      for(int i=0;i<win;i++)
        {
         double h=H(i),l=L(i),pc=C(i+1);
         tr[i]=MathMax(h-l,MathMax(MathAbs(h-pc),MathAbs(l-pc)));
         vol[i]=(double)m_r[i].tick_volume;
        }
      int g=0;
      for(int i=1;i<win-1;i++)
        {
         double up=L(i-1)-H(i+1);
         double dn=L(i+1)-H(i-1);
         double v=MathMax(up,dn);
         if(v>0.0) { gaps[g]=v; g++; }
        }
      m_unit=SmcPercentile(tr,0.50);
      m_vol_med=SmcPercentile(vol,0.50);
      if(g>3) { ArrayResize(gaps,g); m_gap_thr=SmcPercentile(gaps,0.70); }
      else      m_gap_thr=m_unit*0.35;

      //--- adaptive swing sensitivity: match the market's own rhythm
      int    best=3;
      double best_err=1e9;
      for(int len=2;len<=6;len++)
        {
         int cnt=0;
         for(int i=len;i<win-len;i++)
            if(IsPivotHigh(i,len) || IsPivotLow(i,len)) cnt++;
         double density=SmcSafeDiv((double)cnt,(double)(win-2*len),0.0);
         double err=MathAbs(density-0.125);
         if(err<best_err) { best_err=err; best=len; }
        }
      m_pivot=best;
      m_ipivot=(int)MathMax(1,best/2);
     }

   void              PushSwing(const int dir,const int shift)
     {
      SSwing s;
      s.dir=dir;
      s.shift=shift;
      s.time=T(shift);
      s.price=(dir==DIR_BULL?H(shift):L(shift));
      s.swept=false;
      s.swept_time=0;
      int n=ArraySize(m_swings);
      ArrayResize(m_swings,n+1);
      m_swings[n]=s;
      if(ArraySize(m_swings)>SMC_MAX_SWINGS)
        {
         int cut=ArraySize(m_swings)-SMC_MAX_SWINGS;
         ArrayRemove(m_swings,0,cut);
        }
     }

   void              PushEvent(const int kind,const int dir,const bool internal_,
                               const double level,const datetime tm,const datetime origin)
     {
      SStructEvent e;
      e.kind=kind; e.dir=dir; e.internal=internal_;
      e.level=level; e.time=tm; e.origin=origin;
      int n=ArraySize(m_events);
      ArrayResize(m_events,n+1);
      m_events[n]=e;
      if(ArraySize(m_events)>SMC_MAX_EVENTS)
         ArrayRemove(m_events,0,ArraySize(m_events)-SMC_MAX_EVENTS);
      if(!internal_)
        {
         if(kind==EV_CHOCH) { m_last_choch=tm; m_last_choch_dir=dir; }
         else               { m_last_bos=tm;   m_last_bos_dir=dir;   }
        }
     }

   bool              HasImbalance(const int from,const int to,const int dir)
     {
      //--- from (newer, smaller index) .. to (older, larger index)
      for(int i=from+1;i<to;i++)
        {
         if(i-1<0 || i+1>=m_bars) continue;
         if(dir==DIR_BULL && L(i-1)-H(i+1)>=m_gap_thr) return(true);
         if(dir==DIR_BEAR && L(i+1)-H(i-1)>=m_gap_thr) return(true);
        }
      return(false);
     }

   void              PushZone(const int kind,const int dir,const double top,const double bottom,
                              const datetime from,const datetime active,const double displacement,
                              const bool has_fvg,const double vol_ratio,
                              const double idm=0.0,const datetime idm_time=0)
     {
      if(top<=bottom) return;
      SZone z;
      z.kind=kind; z.dir=dir; z.top=top; z.bottom=bottom;
      z.t_from=from; z.t_active=active; z.t_to=from;
      z.idm=idm; z.idm_time=idm_time; z.idm_taken=false;
      z.mitigated=false; z.broken=false;
      z.displacement=displacement;
      z.has_fvg=has_fvg;
      z.vol_ratio=vol_ratio;
      z.uid=++m_uid;
      //--- quality built only from measured quantities
      double d_sc=SmcClamp(displacement/3.0,0.0,1.0);           // 3 median candles = full marks
      double v_sc=SmcClamp((vol_ratio-1.0)/1.5,0.0,1.0);
      double f_sc=(has_fvg?1.0:0.0);
      double w_sc=SmcClamp(1.0-SmcSafeDiv(top-bottom,m_unit*3.0,1.0),0.0,1.0); // tight zones score better
      z.strength=SmcClamp(0.40*d_sc+0.25*f_sc+0.20*v_sc+0.15*w_sc,0.0,1.0);
      int n=ArraySize(m_zones);
      ArrayResize(m_zones,n+1);
      m_zones[n]=z;
     }

   //+---------------------------------------------------------------+
   //| Inducement (IDM)                                                |
   //|                                                                 |
   //| The first valid pullback inside the leg that produced the break. |
   //| Traders who buy that shallow pullback leave their stops just     |
   //| behind it, which is the liquidity price is expected to run       |
   //| before it is drawn back to the real point of interest. The zone  |
   //| behind it is not treated as armed until that pullback has been   |
   //| taken.                                                           |
   //|                                                                 |
   //| break_bar  = the bar whose close broke structure (newer)         |
   //| origin_bar = the order block candle at the start of the leg      |
   //+---------------------------------------------------------------+
   bool              FindInducement(const int dir,const int break_bar,const int origin_bar,
                                    double &idm,datetime &idm_time)
     {
      idm=0.0; idm_time=0;
      if(origin_bar-1<break_bar+1) return(false);            // impulse with no interior bars
      //--- nearest pullback to the point of interest = the first one
      //--- that formed inside the leg, so scan from the origin forward
      for(int pass=0;pass<2;pass++)
        {
         int len=(pass==0?m_ipivot:1);
         for(int p=origin_bar-1;p>=break_bar+1;p--)
           {
            if(p-len<0 || p+len>=m_bars) continue;
            if(dir==DIR_BULL && IsPivotLow(p,len))  { idm=L(p); idm_time=T(p); return(true); }
            if(dir==DIR_BEAR && IsPivotHigh(p,len)) { idm=H(p); idm_time=T(p); return(true); }
           }
        }
      return(false);
     }

   //--- build the order block that produced a structural break -------
   void              BuildOrderBlock(const int dir,const int break_bar,const int origin_bar)
     {
      if(origin_bar<=break_bar) return;
      int j=break_bar;
      if(dir==DIR_BULL)
        {
         int lowest=break_bar;
         for(int k=break_bar;k<=origin_bar && k<m_bars;k++)
            if(L(k)<L(lowest)) lowest=k;
         j=lowest;
         for(int k=lowest;k<=MathMin(origin_bar,lowest+3) && k<m_bars;k++)
            if(C(k)<O(k)) { j=k; break; }
        }
      else
        {
         int highest=break_bar;
         for(int k=break_bar;k<=origin_bar && k<m_bars;k++)
            if(H(k)>H(highest)) highest=k;
         j=highest;
         for(int k=highest;k<=MathMin(origin_bar,highest+3) && k<m_bars;k++)
            if(C(k)>O(k)) { j=k; break; }
        }
      if(j<0 || j>=m_bars) return;
      double disp=SmcSafeDiv(MathAbs(C(break_bar)-(dir==DIR_BULL?L(j):H(j))),m_unit,0.0);
      bool   fvg =HasImbalance(break_bar,j,dir);
      double vr  =SmcSafeDiv((double)m_r[j].tick_volume,m_vol_med,1.0);
      double idm=0.0;
      datetime idm_t=0;
      FindInducement(dir,break_bar,j,idm,idm_t);
      PushZone(ZONE_OB,dir,H(j),L(j),T(j),T(break_bar),disp,fvg,vr,idm,idm_t);
     }

   //--- single pass over history: pivots, structure, order blocks ----
   void              MapStructure(void)
     {
      ArrayFree(m_swings);
      ArrayFree(m_events);
      ArrayFree(m_zones);
      m_trend=DIR_NONE; m_itrend=DIR_NONE;
      m_last_choch=0; m_last_bos=0; m_last_choch_dir=DIR_NONE; m_last_bos_dir=DIR_NONE;

      int n=m_bars;
      if(n<40) return;
      int Lp=m_pivot, Li=m_ipivot;

      double sh=0,sl=0,ish=0,isl=0;
      int    sh_i=-1,sl_i=-1,ish_i=-1,isl_i=-1;

      int start=(int)MathMin(n-2,700);
      for(int b=start;b>=1;b--)      // oldest -> newest, closed bars only
        {
         //--- pivots that become visible at this bar
         int p=b+Lp;
         if(p+Lp<=n-1)
           {
            if(IsPivotHigh(p,Lp)) { sh=H(p); sh_i=p; PushSwing(DIR_BULL,p); }
            if(IsPivotLow(p,Lp))  { sl=L(p); sl_i=p; PushSwing(DIR_BEAR,p); }
           }
         int pi=b+Li;
         if(pi+Li<=n-1)
           {
            if(IsPivotHigh(pi,Li)) { ish=H(pi); ish_i=pi; }
            if(IsPivotLow(pi,Li))  { isl=L(pi); isl_i=pi; }
           }

         double c=C(b);

         //--- swing structure -----------------------------------------
         if(sh_i>0 && c>sh)
           {
            int kind=(m_trend==DIR_BEAR?EV_CHOCH:EV_BOS);
            PushEvent(kind,DIR_BULL,false,sh,T(b),T(sh_i));
            BuildOrderBlock(DIR_BULL,b,sh_i);
            m_trend=DIR_BULL;
            sh_i=-1;
           }
         else if(sl_i>0 && c<sl)
           {
            int kind=(m_trend==DIR_BULL?EV_CHOCH:EV_BOS);
            PushEvent(kind,DIR_BEAR,false,sl,T(b),T(sl_i));
            BuildOrderBlock(DIR_BEAR,b,sl_i);
            m_trend=DIR_BEAR;
            sl_i=-1;
           }

         //--- internal structure --------------------------------------
         if(ish_i>0 && c>ish)
           {
            int kind=(m_itrend==DIR_BEAR?EV_CHOCH:EV_BOS);
            PushEvent(kind,DIR_BULL,true,ish,T(b),T(ish_i));
            if(kind==EV_CHOCH) BuildOrderBlock(DIR_BULL,b,ish_i);
            m_itrend=DIR_BULL;
            ish_i=-1;
           }
         else if(isl_i>0 && c<isl)
           {
            int kind=(m_itrend==DIR_BULL?EV_CHOCH:EV_BOS);
            PushEvent(kind,DIR_BEAR,true,isl,T(b),T(isl_i));
            if(kind==EV_CHOCH) BuildOrderBlock(DIR_BEAR,b,isl_i);
            m_itrend=DIR_BEAR;
            isl_i=-1;
           }
        }
     }

   //--- fair value gaps of the recent tape ---------------------------
   void              MapFvg(void)
     {
      int look=(int)MathMin(m_bars-2,250);
      for(int i=look;i>=2;i--)
        {
         if(i-1<0 || i+1>=m_bars) continue;
         double up=L(i-1)-H(i+1);
         double dn=L(i+1)-H(i-1);
         if(up>=m_gap_thr)
           {
            double vr=SmcSafeDiv((double)m_r[i].tick_volume,m_vol_med,1.0);
            PushZone(ZONE_FVG,DIR_BULL,L(i-1),H(i+1),T(i+1),T(i-1),SmcSafeDiv(up,m_unit,0.0),true,vr);
           }
         else if(dn>=m_gap_thr)
           {
            double vr=SmcSafeDiv((double)m_r[i].tick_volume,m_vol_med,1.0);
            PushZone(ZONE_FVG,DIR_BEAR,L(i+1),H(i-1),T(i+1),T(i-1),SmcSafeDiv(dn,m_unit,0.0),true,vr);
           }
        }
     }

   //--- mitigation / invalidation of every stored zone ---------------
   void              UpdateZones(void)
     {
      int zn=ArraySize(m_zones);
      for(int z=0;z<zn;z++)
        {
         //--- mitigation is only counted once price has displaced away
         //--- from the zone, otherwise the candle that created it would
         //--- immediately mark it as tapped
         int from=iBarShiftLocal(m_zones[z].t_active);
         if(from<0) from=iBarShiftLocal(m_zones[z].t_from);
         if(from<0) continue;
         m_zones[z].t_to=T(1);
         m_zones[z].idm_taken=false;
         for(int b=from-1;b>=1;b--)
           {
            if(m_zones[z].dir==DIR_BULL)
              {
               if(m_zones[z].idm>0.0 && L(b)<m_zones[z].idm) m_zones[z].idm_taken=true;
               if(L(b)<=m_zones[z].top) m_zones[z].mitigated=true;
               if(C(b)< m_zones[z].bottom) { m_zones[z].broken=true; m_zones[z].t_to=T(b); break; }
              }
            else
              {
               if(m_zones[z].idm>0.0 && H(b)>m_zones[z].idm) m_zones[z].idm_taken=true;
               if(H(b)>=m_zones[z].bottom) m_zones[z].mitigated=true;
               if(C(b)> m_zones[z].top) { m_zones[z].broken=true; m_zones[z].t_to=T(b); break; }
              }
           }
        }
      //--- drop broken / stale zones, keep the freshest ones
      SZone keep[];
      int kept=0;
      for(int z=zn-1;z>=0 && kept<SMC_MAX_ZONES;z--)
        {
         if(m_zones[z].broken) continue;
         ArrayResize(keep,kept+1);
         keep[kept]=m_zones[z];
         kept++;
        }
      ArrayFree(m_zones);
      ArrayResize(m_zones,kept);
      for(int i=0;i<kept;i++) m_zones[i]=keep[kept-1-i];   // back to chronological order
     }

   int               iBarShiftLocal(const datetime tm)
     {
      for(int i=0;i<m_bars;i++)
         if(m_r[i].time<=tm) return(i);
      return(-1);
     }

   //--- equal highs / lows + swing liquidity -------------------------
   void              MapLiquidity(void)
     {
      ArrayFree(m_liq);
      int sn=ArraySize(m_swings);
      if(sn<2) return;
      double tol=m_unit*0.15;

      //--- equal highs / lows: two swings of the same kind at the same price
      for(int i=sn-1;i>=1;i--)
        {
         for(int j=i-1;j>=MathMax(0,i-6);j--)
           {
            if(m_swings[i].dir!=m_swings[j].dir) continue;
            if(MathAbs(m_swings[i].price-m_swings[j].price)<=tol)
              {
               int kind=(m_swings[i].dir==DIR_BULL?LQ_EQH:LQ_EQL);
               AddLiquidity(kind,m_swings[i].dir,(m_swings[i].price+m_swings[j].price)*0.5,m_swings[i].time,0.85);
               break;
              }
           }
        }
      //--- the most recent untouched swing extremes
      for(int i=sn-1;i>=MathMax(0,sn-10);i--)
        {
         int kind=(m_swings[i].dir==DIR_BULL?LQ_SWING_H:LQ_SWING_L);
         AddLiquidity(kind,m_swings[i].dir,m_swings[i].price,m_swings[i].time,0.55);
        }
      MarkSweptPools();
     }

   void              MarkSweptPools(void)
     {
      int ln=ArraySize(m_liq);
      for(int i=0;i<ln;i++)
        {
         int from=iBarShiftLocal(m_liq[i].time);
         if(from<0) continue;
         for(int b=from-1;b>=1;b--)
           {
            if(m_liq[i].dir==DIR_BULL && H(b)>m_liq[i].price) { m_liq[i].swept=true; m_liq[i].swept_time=T(b); break; }
            if(m_liq[i].dir==DIR_BEAR && L(b)<m_liq[i].price) { m_liq[i].swept=true; m_liq[i].swept_time=T(b); break; }
           }
        }
     }

   //--- dealing range -> premium / discount --------------------------
   void              MapRange(void)
     {
      int sn=ArraySize(m_swings);
      m_range_hi=0; m_range_lo=0; m_range_hi_t=0; m_range_lo_t=0;
      double hi=-DBL_MAX,lo=DBL_MAX;
      datetime ht=0,lt=0;
      int found_h=0,found_l=0;
      for(int i=sn-1;i>=0 && (found_h<2 || found_l<2);i--)
        {
         if(m_swings[i].dir==DIR_BULL && found_h<2)
           { if(m_swings[i].price>hi) { hi=m_swings[i].price; ht=m_swings[i].time; } found_h++; }
         if(m_swings[i].dir==DIR_BEAR && found_l<2)
           { if(m_swings[i].price<lo) { lo=m_swings[i].price; lt=m_swings[i].time; } found_l++; }
        }
      //--- extend with anything the tape did after those swings
      int hb=iBarShiftLocal(ht),lb=iBarShiftLocal(lt);
      int scan=(int)MathMax(hb,lb);
      if(scan>0)
         for(int b=scan;b>=1;b--)
           {
            if(H(b)>hi) { hi=H(b); ht=T(b); }
            if(L(b)<lo) { lo=L(b); lt=T(b); }
           }
      if(hi>lo) { m_range_hi=hi; m_range_lo=lo; m_range_hi_t=ht; m_range_lo_t=lt; }
     }

   //--- most recent stop raid on any known pool ----------------------
   void              DetectSweep(void)
     {
      m_sweep_valid=false;
      m_sweep_reaction_dir=DIR_NONE;
      m_sweep_quality=0.0;
      m_sweep_pool="";
      int window=(int)MathMax(4,m_pivot*4);
      int ln=ArraySize(m_liq);
      double best_q=0.0;
      for(int b=1;b<=window && b<m_bars-1;b++)
        {
         double tr=MathMax(H(b)-L(b),1e-10);
         for(int i=0;i<ln;i++)
           {
            double p=m_liq[i].price;
            if(m_liq[i].dir==DIR_BULL)
              {
               //--- raid above buy-side liquidity, close back below = bearish reaction
               if(H(b)>p && C(b)<p)
                 {
                  double wick=H(b)-MathMax(C(b),O(b));
                  double q=SmcClamp(SmcSafeDiv(wick,tr,0.0),0.0,1.0)*m_liq[i].weight
                           *SmcClamp(1.0-(double)(b-1)/(double)window,0.15,1.0);
                  if(q>best_q)
                    {
                     best_q=q; m_sweep_valid=true; m_sweep_reaction_dir=DIR_BEAR;
                     m_sweep_price=p; m_sweep_extreme=H(b); m_sweep_time=T(b);
                     m_sweep_age=b; m_sweep_quality=q; m_sweep_pool=SmcLiqStr(m_liq[i].kind);
                    }
                 }
              }
            else
              {
               if(L(b)<p && C(b)>p)
                 {
                  double wick=MathMin(C(b),O(b))-L(b);
                  double q=SmcClamp(SmcSafeDiv(wick,tr,0.0),0.0,1.0)*m_liq[i].weight
                           *SmcClamp(1.0-(double)(b-1)/(double)window,0.15,1.0);
                  if(q>best_q)
                    {
                     best_q=q; m_sweep_valid=true; m_sweep_reaction_dir=DIR_BULL;
                     m_sweep_price=p; m_sweep_extreme=L(b); m_sweep_time=T(b);
                     m_sweep_age=b; m_sweep_quality=q; m_sweep_pool=SmcLiqStr(m_liq[i].kind);
                    }
                 }
              }
           }
        }
     }

public:
                     CSmcEngine(void): m_label(""), m_bars(0), m_unit(0), m_gap_thr(0), m_vol_med(1),
                                       m_pivot(3), m_ipivot(1), m_trend(DIR_NONE), m_itrend(DIR_NONE),
                                       m_last_choch(0), m_last_choch_dir(DIR_NONE), m_last_bos(0),
                                       m_last_bos_dir(DIR_NONE), m_range_hi(0), m_range_lo(0),
                                       m_range_hi_t(0), m_range_lo_t(0), m_sweep_valid(false),
                                       m_sweep_reaction_dir(DIR_NONE), m_sweep_price(0), m_sweep_extreme(0),
                                       m_sweep_time(0), m_sweep_age(0), m_sweep_quality(0), m_sweep_pool(""),
                                       m_uid(0) {}

   void              SetLabel(const string s) { m_label=s; }
   string            Label(void) const { return(m_label); }

   bool              Analyze(const MqlRates &rates[])
     {
      m_bars=ArraySize(rates);
      if(m_bars<60) return(false);
      ArrayResize(m_r,m_bars);
      for(int i=0;i<m_bars;i++) m_r[i]=rates[i];   // caller passes a series array: index 0 = newest
      Calibrate();
      if(m_unit<=0.0) return(false);
      MapStructure();
      MapFvg();
      UpdateZones();
      MapLiquidity();
      MapRange();
      DetectSweep();
      return(true);
     }

   void              AddLiquidity(const int kind,const int dir,const double price,const datetime tm,const double weight)
     {
      if(price<=0.0) return;
      int n=ArraySize(m_liq);
      for(int i=0;i<n;i++)
         if(m_liq[i].kind==kind && MathAbs(m_liq[i].price-price)<m_unit*0.05) return;   // dedupe
      SLiquidity q;
      q.kind=kind; q.dir=dir; q.price=price; q.time=tm;
      q.swept=false; q.swept_time=0; q.weight=weight;
      ArrayResize(m_liq,n+1);
      m_liq[n]=q;
      if(ArraySize(m_liq)>SMC_MAX_LIQ) ArrayRemove(m_liq,0,ArraySize(m_liq)-SMC_MAX_LIQ);
     }

   //--- re-run sweep detection after external pools were added -------
   void              RefreshSweeps(void) { MarkSweptPools(); DetectSweep(); }

   //--- state -------------------------------------------------------
   int               Trend(void)         const { return(m_trend);  }
   int               InternalTrend(void) const { return(m_itrend); }
   double            Unit(void)          const { return(m_unit);   }
   double            GapThreshold(void)  const { return(m_gap_thr);}
   int               PivotLen(void)      const { return(m_pivot);  }
   datetime          LastChochTime(void) const { return(m_last_choch); }
   int               LastChochDir(void)  const { return(m_last_choch_dir); }
   datetime          LastBosTime(void)   const { return(m_last_bos); }
   int               LastBosDir(void)    const { return(m_last_bos_dir); }

   bool              SweepValid(void)    const { return(m_sweep_valid); }
   int               SweepDir(void)      const { return(m_sweep_reaction_dir); }
   double            SweepPrice(void)    const { return(m_sweep_price); }
   double            SweepExtreme(void)  const { return(m_sweep_extreme); }
   datetime          SweepTime(void)     const { return(m_sweep_time); }
   int               SweepAge(void)      const { return(m_sweep_age); }
   double            SweepQuality(void)  const { return(m_sweep_quality); }
   string            SweepPool(void)     const { return(m_sweep_pool); }

   bool              Range(double &hi,double &lo) { hi=m_range_hi; lo=m_range_lo; return(hi>lo); }
   datetime          RangeHiTime(void) const { return(m_range_hi_t); }
   datetime          RangeLoTime(void) const { return(m_range_lo_t); }

   //--- 0 = at the low of the range, 1 = at the high -----------------
   double            RangePosition(const double price)
     {
      if(m_range_hi<=m_range_lo) return(0.5);
      return(SmcClamp((price-m_range_lo)/(m_range_hi-m_range_lo),0.0,1.0));
     }

   //--- collections -------------------------------------------------
   int               SwingCount(void) { return(ArraySize(m_swings)); }
   bool              GetSwing(const int i,SSwing &s)
     { if(i<0 || i>=ArraySize(m_swings)) return(false); s=m_swings[i]; return(true); }

   int               ZoneCount(void) { return(ArraySize(m_zones)); }
   bool              GetZone(const int i,SZone &z)
     { if(i<0 || i>=ArraySize(m_zones)) return(false); z=m_zones[i]; return(true); }

   int               EventCount(void) { return(ArraySize(m_events)); }
   bool              GetEvent(const int i,SStructEvent &e)
     { if(i<0 || i>=ArraySize(m_events)) return(false); e=m_events[i]; return(true); }

   int               LiqCount(void) { return(ArraySize(m_liq)); }
   bool              GetLiq(const int i,SLiquidity &q)
     { if(i<0 || i>=ArraySize(m_liq)) return(false); q=m_liq[i]; return(true); }

   //--- best unmitigated zone in the direction dir that price is
   //--- interacting with right now (or is about to)
   bool              FindActiveZone(const int dir,const double price,const double reach,SZone &out)
     {
      bool found=false;
      double best=-1.0;
      int zn=ArraySize(m_zones);
      for(int i=0;i<zn;i++)
        {
         if(m_zones[i].dir!=dir || m_zones[i].broken) continue;
         double top=m_zones[i].top,bot=m_zones[i].bottom;
         bool inside=(price<=top+reach && price>=bot-reach);
         if(!inside) continue;
         //--- prefer fresh, strong, unmitigated zones close to price
         double freshness=(m_zones[i].mitigated?0.55:1.0);
         double dist=MathAbs(price-(top+bot)*0.5);
         double prox=SmcClamp(1.0-SmcSafeDiv(dist,MathMax(reach,m_unit),1.0),0.0,1.0);
         double sc=m_zones[i].strength*freshness*(0.6+0.4*prox);
         if(sc>best) { best=sc; out=m_zones[i]; found=true; }
        }
      return(found);
     }

   //--- overlapping zone of the other kind (OB backed by FVG etc.) ---
   bool              HasOverlap(const int dir,const double top,const double bottom,const int kind)
     {
      int zn=ArraySize(m_zones);
      for(int i=0;i<zn;i++)
        {
         if(m_zones[i].dir!=dir || m_zones[i].kind!=kind || m_zones[i].broken) continue;
         if(m_zones[i].bottom<=top && m_zones[i].top>=bottom) return(true);
        }
      return(false);
     }

   //--- nearest unswept liquidity used as a profit objective ---------
   bool              NextTarget(const int dir,const double price,const double min_dist,
                                double &target,string &name,double &weight)
     {
      bool found=false;
      double best=DBL_MAX;
      int ln=ArraySize(m_liq);
      for(int i=0;i<ln;i++)
        {
         if(m_liq[i].swept) continue;
         double p=m_liq[i].price;
         if(dir==DIR_BULL && p>price+min_dist && p-price<best)
           { best=p-price; target=p; name=SmcLiqStr(m_liq[i].kind); weight=m_liq[i].weight; found=true; }
         if(dir==DIR_BEAR && p<price-min_dist && price-p<best)
           { best=price-p; target=p; name=SmcLiqStr(m_liq[i].kind); weight=m_liq[i].weight; found=true; }
        }
      return(found);
     }

   //--- furthest meaningful objective (range extreme) ----------------
   bool              RangeTarget(const int dir,const double price,double &target)
     {
      if(m_range_hi<=m_range_lo) return(false);
      if(dir==DIR_BULL && m_range_hi>price) { target=m_range_hi; return(true); }
      if(dir==DIR_BEAR && m_range_lo<price) { target=m_range_lo; return(true); }
      return(false);
     }
  };

#endif // __SMC_ENGINE_MQH__
