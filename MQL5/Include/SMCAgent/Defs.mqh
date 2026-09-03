//+------------------------------------------------------------------+
//|                                                         Defs.mqh |
//|             SMC AI Agent - shared types, constants and math tools |
//|                                                                  |
//|  Design rule of this project:                                    |
//|  ------------------------------------------------------------    |
//|  No trading decision in this code base is driven by a fixed,      |
//|  user-optimised technical parameter (no "RSI(14) < 30" logic).    |
//|  Every threshold used by the decision engine is derived at run    |
//|  time from the live distribution of the price action that is      |
//|  visible on the chart (percentiles / z-scores / rhythm counts).   |
//+------------------------------------------------------------------+
#ifndef __SMC_DEFS_MQH__
#define __SMC_DEFS_MQH__

#define SMC_AGENT_NAME     "SMC AI Agent"
#define SMC_AGENT_VERSION  "1.00"

//--- field separator for the files the agent writes and reads back.
//--- Stated explicitly rather than relying on FileOpen's default, so a
//--- change of default can never orphan a stored model.
#define SMC_FIELD_SEP      ';'

//--- directions (plain ints, so that -1 is always legal) ------------
#define DIR_NONE   0
#define DIR_BULL   1
#define DIR_BEAR  -1

//--- zone kinds -----------------------------------------------------
#define ZONE_OB       0   // order block (last opposing candle before displacement)
#define ZONE_FVG      1   // fair value gap / imbalance
#define ZONE_BREAKER  2   // failed order block that flipped polarity

//--- liquidity pool kinds -------------------------------------------
#define LQ_EQH      0     // equal highs
#define LQ_EQL      1     // equal lows
#define LQ_PDH      2     // previous day high
#define LQ_PDL      3     // previous day low
#define LQ_PWH      4     // previous week high
#define LQ_PWL      5     // previous week low
#define LQ_ASIA_H   6     // asian / accumulation range high
#define LQ_ASIA_L   7     // asian / accumulation range low
#define LQ_SWING_H  8     // major swing high
#define LQ_SWING_L  9     // major swing low
#define LQ_IDM     10     // inducement: the first pullback inside the leg that broke structure

//--- structure event kinds ------------------------------------------
#define EV_BOS    0
#define EV_CHOCH  1

//+------------------------------------------------------------------+
//| Confirmed swing point                                            |
//+------------------------------------------------------------------+
struct SSwing
  {
   datetime          time;
   double            price;
   int               shift;      // series index at the time of detection
   int               dir;        // DIR_BULL = swing high, DIR_BEAR = swing low
   bool              swept;      // liquidity above/below it has been taken
   datetime          swept_time;
  };

//+------------------------------------------------------------------+
//| Price zone (order block / fair value gap / breaker)              |
//+------------------------------------------------------------------+
struct SZone
  {
   int               kind;       // ZONE_*
   int               dir;        // DIR_BULL = demand, DIR_BEAR = supply
   double            top;
   double            bottom;
   datetime          t_from;     // left edge of the drawn zone
   datetime          t_active;   // moment price displaced away from it: mitigation counts from here
   datetime          t_to;
   bool              mitigated;
   bool              broken;
   double            strength;   // 0..1, quality score built from live stats
   double            displacement; // size of the leg that created it, in local TR units
   bool              has_fvg;    // order block backed by an imbalance
   double            vol_ratio;  // creating candle volume vs local distribution
   //--- inducement: the first valid pullback inside the leg that this
   //--- zone produced. The zone is not considered "armed" until that
   //--- pullback liquidity has been run.
   double            idm;        // price of the inducement (0 = none identified)
   datetime          idm_time;
   bool              idm_taken;
   long              uid;
  };

//+------------------------------------------------------------------+
//| Liquidity pool (resting stops)                                   |
//+------------------------------------------------------------------+
struct SLiquidity
  {
   int               kind;       // LQ_*
   int               dir;        // DIR_BULL = buy-side (above price), DIR_BEAR = sell-side
   double            price;
   datetime          time;
   bool              swept;
   datetime          swept_time;
   double            weight;     // relative importance 0..1
  };

//+------------------------------------------------------------------+
//| Market structure event                                           |
//+------------------------------------------------------------------+
struct SStructEvent
  {
   int               kind;       // EV_BOS / EV_CHOCH
   int               dir;        // direction of the break
   bool              internal;   // internal (minor) or swing (major) structure
   double            level;      // broken level
   datetime          time;       // time of the breaking bar
   datetime          origin;     // time of the swing that was broken
  };

//+------------------------------------------------------------------+
//| A single confluence factor as evaluated on the closed bar        |
//+------------------------------------------------------------------+
struct SFactor
  {
   string            name;
   double            raw;        // raw measured value (for the log)
   double            score;      // -1..+1, signed towards bull(+)/bear(-)
   double            weight;     // current (learned) weight
   double            contrib;    // score * weight
   string            note;       // human readable explanation
   bool              veto;       // hard blocker
  };

//+------------------------------------------------------------------+
//| Trade signal produced by the agent                               |
//+------------------------------------------------------------------+
struct SSignal
  {
   bool              valid;
   int               dir;
   double            entry;
   double            sl;
   double            tp1;
   double            tp2;
   double            prob;        // model probability of success 0..1
   double            raw_score;   // weighted confluence score
   double            rr1;
   double            rr2;
   string            model;       // playbook name
   string            rationale;   // natural language explanation
   datetime          bar_time;
   double            zone_top;
   double            zone_bottom;
   double            idm;         // inducement guarding the zone (0 = none)
   bool              idm_taken;
  };

//+------------------------------------------------------------------+
//| Math helpers                                                     |
//+------------------------------------------------------------------+
double SmcClamp(const double v,const double lo,const double hi)
  {
   if(v<lo) return(lo);
   if(v>hi) return(hi);
   return(v);
  }

double SmcSafeDiv(const double a,const double b,const double def=0.0)
  {
   if(MathAbs(b)<DBL_EPSILON) return(def);
   return(a/b);
  }

double SmcSigmoid(const double x)
  {
   if(x>30.0)  return(1.0);
   if(x<-30.0) return(0.0);
   return(1.0/(1.0+MathExp(-x)));
  }

//--- percentile of an (unsorted) array; p in 0..1 -------------------
double SmcPercentile(const double &src[],const double p)
  {
   int n=ArraySize(src);
   if(n<=0) return(0.0);
   double tmp[];
   ArrayResize(tmp,n);
   ArrayCopy(tmp,src,0,0,n);
   ArraySort(tmp);
   double pos=SmcClamp(p,0.0,1.0)*(n-1);
   int    i0=(int)MathFloor(pos);
   int    i1=(int)MathMin(i0+1,n-1);
   double f =pos-i0;
   return(tmp[i0]*(1.0-f)+tmp[i1]*f);
  }

double SmcMedian(const double &src[]) { return(SmcPercentile(src,0.5)); }

double SmcMean(const double &src[])
  {
   int n=ArraySize(src);
   if(n<=0) return(0.0);
   double s=0.0;
   for(int i=0;i<n;i++) s+=src[i];
   return(s/n);
  }

double SmcStdev(const double &src[])
  {
   int n=ArraySize(src);
   if(n<2) return(0.0);
   double m=SmcMean(src),s=0.0;
   for(int i=0;i<n;i++) s+=(src[i]-m)*(src[i]-m);
   return(MathSqrt(s/(n-1)));
  }

//--- rank of value inside a sample: 0..1 (empirical CDF) ------------
double SmcRank(const double &src[],const double v)
  {
   int n=ArraySize(src);
   if(n<=0) return(0.5);
   int below=0;
   for(int i=0;i<n;i++) if(src[i]<v) below++;
   return((double)below/(double)n);
  }

//--- Tie-aware empirical rank, 0..1. Ties count half, so a CONSTANT
//--- sample returns 0.5 rather than 0 - which matters, because a
//--- constant measurement carries no information and must score neutral
//--- instead of maximally good.
double SmcRankTies(const double &src[],const double v)
  {
   int n=ArraySize(src);
   if(n<=0) return(0.5);
   int below=0,equal=0;
   for(int i=0;i<n;i++)
     {
      if(src[i]<v-1e-12)      below++;
      else if(src[i]<=v+1e-12) equal++;
     }
   return(((double)below+0.5*(double)equal)/(double)n);
  }

//--- map a value to -1..+1 using a soft saturation ------------------
double SmcSquash(const double x,const double scale)
  {
   if(scale<=0.0) return(0.0);
   return(SmcClamp(MathTanh(x/scale),-1.0,1.0));
  }

//+------------------------------------------------------------------+
//| Time helpers                                                     |
//+------------------------------------------------------------------+
//--- "now" on the trade server.
//--- TimeCurrent() is the timestamp of the last known tick, so it goes stale
//--- over weekends, holidays and quiet books. TimeTradeServer() is the
//--- calculated current server time and keeps running while the market is
//--- closed, which is what news timing and the FTMO daily reset need.
datetime SmcNow()
  {
   datetime t=TimeTradeServer();
   if(t<=0) t=TimeCurrent();
   return(t);
  }

//--- broker server time minus GMT, rounded to the nearest hour.
//--- Recomputed live, so a broker daylight-saving change is picked up
//--- automatically. Returns 99 if it cannot be established.
int SmcServerGmtOffsetHours()
  {
   datetime srv=SmcNow();
   datetime gmt=TimeGMT();
   if(srv<=0 || gmt<=0) return(99);
   double h=((double)((long)srv-(long)gmt))/3600.0;
   if(MathAbs(h)>14.5) return(99);          // implausible: bad clock or tester
   return((int)MathRound(h));
  }

//--- NOTE: raw "hour in GMT" helpers used to live here. They were removed
//--- with the daylight saving rework: session windows are exchange-local
//--- (see TimeZones.mqh) and reintroducing a fixed-GMT hour would silently
//--- bring back the winter offset bug.

datetime SmcDayStart(const datetime t)
  {
   MqlDateTime dt;
   TimeToStruct(t,dt);
   dt.hour=0; dt.min=0; dt.sec=0;
   return(StructToTime(dt));
  }

int SmcDayOfWeek(const datetime t)
  {
   MqlDateTime dt;
   TimeToStruct(t,dt);
   return(dt.day_of_week);
  }

//--- monday 00:00 of the week that contains t -----------------------
datetime SmcWeekStart(const datetime t)
  {
   MqlDateTime dt;
   TimeToStruct(t,dt);
   int dow=dt.day_of_week;              // 0=sunday
   int back=(dow==0?6:dow-1);
   return(SmcDayStart(t)-(datetime)(back*86400));
  }

//+------------------------------------------------------------------+
//| Formatting helpers                                               |
//+------------------------------------------------------------------+
string SmcDirStr(const int dir)
  {
   if(dir==DIR_BULL) return("BULLISH");
   if(dir==DIR_BEAR) return("BEARISH");
   return("NEUTRAL");
  }

string SmcDirShort(const int dir)
  {
   if(dir==DIR_BULL) return("BUY");
   if(dir==DIR_BEAR) return("SELL");
   return("--");
  }

string SmcZoneStr(const int kind)
  {
   switch(kind)
     {
      case ZONE_OB:      return("OB");
      case ZONE_FVG:     return("FVG");
      case ZONE_BREAKER: return("BRK");
     }
   return("?");
  }

string SmcLiqStr(const int kind)
  {
   switch(kind)
     {
      case LQ_EQH:     return("EQH");
      case LQ_EQL:     return("EQL");
      case LQ_PDH:     return("PDH");
      case LQ_PDL:     return("PDL");
      case LQ_PWH:     return("PWH");
      case LQ_PWL:     return("PWL");
      case LQ_ASIA_H:  return("ASIA-H");
      case LQ_ASIA_L:  return("ASIA-L");
      case LQ_SWING_H: return("SWING-H");
      case LQ_SWING_L: return("SWING-L");
      case LQ_IDM:     return("IDM");
     }
   return("LQ");
  }

#endif // __SMC_DEFS_MQH__
