//+------------------------------------------------------------------+
//|                                              SMC_Raid_CHoCH.mq5 |
//|                                                                  |
//|  XAUUSD - one Smart Money Concepts setup, traded strictly.       |
//|                                                                  |
//|  BUY                                                             |
//|    1. A SELL-SIDE liquidity pool is raided: a closed candle's low |
//|       trades below the pool and its close comes back above it.    |
//|       Pools = previous day / week low, Asian session low, equal   |
//|       lows, recent swing lows.                                    |
//|    2. Within a few bars, structure breaks UP through the swing    |
//|       high that was standing when the raid happened - the change  |
//|       of character (CHoCH).                                       |
//|    3. Enter at that confirmation close. Stop beyond the raid low. |
//|       Target the nearest unswept BUY-SIDE pool; if none lies far  |
//|       enough away, a measured multiple of the risk is used.       |
//|                                                                  |
//|  SELL is the exact mirror: buy-side pool raided, structure breaks |
//|  DOWN through the standing swing low, stop above the raid high.   |
//|                                                                  |
//|  Nothing else trades. No continuation setups, no order-block      |
//|  retests, no machine learning. If the raid is not followed by a    |
//|  CHoCH inside the confirmation window, the setup expires unused.  |
//|                                                                  |
//|  Self contained: one file, no includes beyond MetaTrader's own    |
//|  Trade library, no indicators, no network access.                 |
//+------------------------------------------------------------------+
#property copyright "SMC Raid + CHoCH"
#property version   "1.00"
#property description "XAUUSD liquidity raid + change of character. One setup, both directions."

#include <Trade/Trade.mqh>

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
input group "=== Setup detection ==="
input int    InpPivotLen        = 0;      // Swing pivot length (0 = adapt to the market's rhythm)
input int    InpConfirmBars     = 6;      // Bars after the raid in which the CHoCH must happen
input double InpMinRejection    = 0.25;   // Minimum rejection wick, as a fraction of the raid candle
input bool   InpUseEqualLevels  = true;   // Include equal highs / lows as pools
input bool   InpUseDayWeek      = true;   // Include previous day / week high and low
input bool   InpUseAsianRange   = true;   // Include the Asian session high and low
input bool   InpUseSwings       = true;   // Include recent swing highs / lows

input group "=== Entry filters ==="
input bool   InpKillzonesOnly   = false;  // Only trade the London and New York killzones
input double InpMaxStopUnits    = 4.0;    // Reject a stop wider than this many median candles
input double InpMinRR           = 1.5;    // Minimum reward:risk to the first objective
input double InpFallbackRR      = 2.0;    // If no pool lies beyond MinRR, use this measured R (0 = no trade)
input double InpMaxSpreadPct    = 20.0;   // Reject if the spread exceeds this % of the stop
input bool   InpRequireHtfAgree = false;  // Require the H4 swing trend to agree

input group "=== Risk ==="
input double InpRiskPercent     = 0.5;    // Risk per trade, % of balance
input double InpMaxDailyLossPct = 3.0;    // Stop trading for the day after this loss %
input double InpFixedLots       = 0.0;    // Override: fixed lot size (0 = risk based)
input int    InpMaxPositions    = 1;      // Maximum open positions

input group "=== Management ==="
input double InpPartialAtR      = 1.0;    // Take partial profit at this R (0 = off)
input double InpPartialPercent  = 50.0;   // Percent closed there
input double InpBreakEvenAtR    = 1.0;    // Move stop to break even at this R (0 = off)
input double InpTrailAfterR     = 1.5;    // Structural trail after this R (0 = off)
input int    InpTimeStopBars    = 0;      // Abandon after N bars below +0.5R (0 = off)

input group "=== Display ==="
input bool   InpShowPools       = true;   // Draw liquidity pools
input bool   InpShowSetups      = true;   // Mark raids, CHoCH and entries
input bool   InpShowPanel       = true;   // Status panel
input int    InpPanelFontSize   = 10;     // Panel font size
input int    InpMagic           = 77220901;
input int    InpSlippage        = 40;

//+------------------------------------------------------------------+
//| Constants and globals                                            |
//+------------------------------------------------------------------+
#define PFX      "SRC_"          // chart object prefix
#define CAL_BARS 400             // calibration window
#define MAX_POOLS 40
#define DIR_BUY   1
#define DIR_SELL -1

CTrade    trade;

//--- price data, index 0 = the bar still forming
MqlRates  rt[];
int       bars=0;

//--- calibration
double    unitTR=0;              // median true range: "one normal candle"
double    volMed=0;
int       pivLen=3;

//--- structure
double    swingHigh=0,swingLow=0;
datetime  swingHighT=0,swingLowT=0;
int       trendDir=0;

//--- liquidity pools
struct Pool
  {
   string   name;
   int      side;                // DIR_BUY = above price (buy-side), DIR_SELL = below
   double   price;
   datetime born;
   bool     swept;
  };
Pool      pools[];

//--- armed setup (the raid waiting for its CHoCH)
bool      armed=false;
int       armDir=0;
double    armExtreme=0;          // the raid candle's low (buy) or high (sell)
double    armCHoCH=0;            // level whose break confirms the setup
datetime  armTime=0;
int       armBar=0;
string    armPool="";
double    armQuality=0;

//--- open trade bookkeeping
ulong     posTicket=0;
ulong     posId=0;
double    posEntry=0,posStop=0,posRisk=0,posTP=0;
int       posDir=0;
datetime  posOpened=0;
bool      donePartial=false,doneBE=false;

//--- day tracking
datetime  dayStamp=0;
double    dayStartEquity=0;
bool      dayBlocked=false;

//--- diagnostics
int       nRaids=0,nCHoCH=0,nTrades=0,nExpired=0;
string    lastNote="starting up";
int       gmtOffset=0;

//+------------------------------------------------------------------+
//| Small helpers                                                    |
//+------------------------------------------------------------------+
double Clamp(double v,double lo,double hi){ return(v<lo?lo:(v>hi?hi:v)); }
double SafeDiv(double a,double b,double d=0.0){ return(MathAbs(b)<DBL_EPSILON?d:a/b); }

double Percentile(const double &src[],double p)
  {
   int n=ArraySize(src);
   if(n<=0) return(0.0);
   double t[];
   ArrayResize(t,n);
   for(int i=0;i<n;i++) t[i]=src[i];
   ArraySort(t);
   double pos=Clamp(p,0.0,1.0)*(n-1);
   int i0=(int)MathFloor(pos), i1=(int)MathMin(i0+1,n-1);
   double f=pos-i0;
   return(t[i0]*(1.0-f)+t[i1]*f);
  }

int VolumeDigits(double step)
  {
   int d=0; double v=step;
   while(v<1.0-1e-9 && d<8){ v*=10.0; d++; }
   return(d);
  }

double H(int i){ return(i>=0 && i<bars?rt[i].high :0.0); }
double L(int i){ return(i>=0 && i<bars?rt[i].low  :0.0); }
double O(int i){ return(i>=0 && i<bars?rt[i].open :0.0); }
double C(int i){ return(i>=0 && i<bars?rt[i].close:0.0); }
datetime T(int i){ return(i>=0 && i<bars?rt[i].time:0); }

//+------------------------------------------------------------------+
//| Daylight saving, computed - no lookup tables, no network         |
//|   America/New_York : 2nd Sun Mar 07:00 UTC -> 1st Sun Nov 06:00  |
//|   Europe/London    : last Sun Mar 01:00 UTC -> last Sun Oct 01:00|
//+------------------------------------------------------------------+
int DaysInMonth(int y,int m)
  {
   if(m==2) return(((y%4==0 && y%100!=0)||y%400==0)?29:28);
   if(m==4||m==6||m==9||m==11) return(30);
   return(31);
  }
datetime MakeUtc(int y,int mo,int d,int h)
  {
   MqlDateTime t; t.year=y; t.mon=mo; t.day=d; t.hour=h; t.min=0; t.sec=0;
   t.day_of_week=0; t.day_of_year=0;
   return(StructToTime(t));
  }
int DowOf(datetime t){ MqlDateTime d; TimeToStruct(t,d); return(d.day_of_week); }
datetime NthSunday(int y,int mo,int nth,int h)
  {
   datetime f=MakeUtc(y,mo,1,h);
   int day=1+((7-DowOf(f))%7)+(nth-1)*7;
   if(day>DaysInMonth(y,mo)) day-=7;
   return(MakeUtc(y,mo,day,h));
  }
datetime LastSunday(int y,int mo,int h)
  {
   int dim=DaysInMonth(y,mo);
   datetime l=MakeUtc(y,mo,dim,h);
   return(MakeUtc(y,mo,dim-DowOf(l),h));
  }
bool UsDst(datetime utc)
  {
   MqlDateTime d; TimeToStruct(utc,d);
   return(utc>=NthSunday(d.year,3,2,7) && utc<NthSunday(d.year,11,1,6));
  }
bool EuDst(datetime utc)
  {
   MqlDateTime d; TimeToStruct(utc,d);
   return(utc>=LastSunday(d.year,3,1) && utc<LastSunday(d.year,10,1));
  }
datetime Shift(datetime t,long s){ return((datetime)((long)t+s)); }
datetime SrvToUtc(datetime srv){ return(Shift(srv,-(long)gmtOffset*3600)); }
double ZoneHour(datetime utc,bool newyork)
  {
   int off=(newyork?(UsDst(utc)?-4:-5):(EuDst(utc)?1:0));
   MqlDateTime d;
   TimeToStruct(Shift(utc,(long)off*3600),d);
   return(d.hour+d.min/60.0);
  }
bool InKillzone(datetime srv)
  {
   datetime u=SrvToUtc(srv);
   double ldn=ZoneHour(u,false), ny=ZoneHour(u,true);
   return((ldn>=7.0 && ldn<10.0) || (ny>=8.0 && ny<11.0));
  }
string SessionName(datetime srv)
  {
   datetime u=SrvToUtc(srv);
   double ldn=ZoneHour(u,false), ny=ZoneHour(u,true);
   if(ldn>=7.0 && ldn<10.0 && ny>=8.0 && ny<11.0) return("London/NY overlap");
   if(ny>=8.0 && ny<11.0)   return("New York killzone");
   if(ldn>=7.0 && ldn<10.0) return("London killzone");
   if(ldn>=0.0 && ldn<7.0)  return("Asian session");
   return("outside killzones");
  }

//--- forward declarations: Refresh() calibrates using the pivot tests
bool IsPivotHigh(int p,int len);
bool IsPivotLow(int p,int len);

//+------------------------------------------------------------------+
//| Data and calibration - closed bars only. Index 0 is still        |
//| forming, and including it drags every statistic toward zero.     |
//+------------------------------------------------------------------+
bool Refresh()
  {
   ArraySetAsSeries(rt,true);
   int got=CopyRates(_Symbol,PERIOD_CURRENT,0,CAL_BARS+120,rt);
   if(got<80) return(false);
   bars=got;

   int win=(int)MathMin(CAL_BARS,bars-2);
   if(win<40) return(false);

   double tr[],vol[];
   ArrayResize(tr,win); ArrayResize(vol,win);
   for(int i=0;i<win;i++)
     {
      int b=i+1;                                   // closed bars only
      double hi=H(b),lo=L(b),pc=C(b+1);
      tr[i]=MathMax(hi-lo,MathMax(MathAbs(hi-pc),MathAbs(lo-pc)));
      vol[i]=(double)rt[b].tick_volume;
     }
   unitTR=Percentile(tr,0.50);
   volMed=Percentile(vol,0.50);
   if(unitTR<=0.0) return(false);

   //--- pivot length: either fixed, or the one whose pivot density
   //--- matches this market's own rhythm (~1 pivot every 8 candles)
   if(InpPivotLen>=2)
      pivLen=InpPivotLen;
   else
     {
      int best=3; double err=1e9;
      for(int len=2;len<=6;len++)
        {
         int cnt=0;
         for(int i=len+1;i<win-len;i++)
            if(IsPivotHigh(i,len) || IsPivotLow(i,len)) cnt++;
         double dens=SafeDiv((double)cnt,(double)(win-2*len),0.0);
         if(MathAbs(dens-0.125)<err){ err=MathAbs(dens-0.125); best=len; }
        }
      pivLen=best;
     }
   return(true);
  }

bool IsPivotHigh(int p,int len)
  {
   if(p-len<0 || p+len>=bars) return(false);
   for(int k=1;k<=len;k++)
     {
      if(H(p)<=H(p-k)) return(false);              // strictly higher on the newer side
      if(H(p)< H(p+k)) return(false);
     }
   return(true);
  }
bool IsPivotLow(int p,int len)
  {
   if(p-len<0 || p+len>=bars) return(false);
   for(int k=1;k<=len;k++)
     {
      if(L(p)>=L(p-k)) return(false);
      if(L(p)> L(p+k)) return(false);
     }
   return(true);
  }

//+------------------------------------------------------------------+
//| Market structure: track the standing swing high and low, and the |
//| trend implied by which one price last broke.                     |
//+------------------------------------------------------------------+
void MapStructure()
  {
   swingHigh=0; swingLow=0; swingHighT=0; swingLowT=0; trendDir=0;
   int scan=(int)MathMin(bars-pivLen-2,500);
   for(int b=scan;b>=1;b--)
     {
      int p=b+pivLen;
      if(p+pivLen<=bars-1)
        {
         if(IsPivotHigh(p,pivLen)){ swingHigh=H(p); swingHighT=T(p); }
         if(IsPivotLow(p,pivLen)) { swingLow =L(p); swingLowT =T(p); }
        }
      if(swingHigh>0.0 && C(b)>swingHigh){ trendDir=DIR_BUY;  swingHigh=0.0; }
      if(swingLow >0.0 && C(b)<swingLow) { trendDir=DIR_SELL; swingLow =0.0; }
     }
   //--- re-establish whichever level was consumed, so a level is always
   //--- available for the next CHoCH test
   for(int p=pivLen+1;p<(int)MathMin(bars-pivLen-1,200);p++)
     {
      if(swingHigh<=0.0 && IsPivotHigh(p,pivLen)){ swingHigh=H(p); swingHighT=T(p); }
      if(swingLow <=0.0 && IsPivotLow(p,pivLen)) { swingLow =L(p); swingLowT =T(p); }
      if(swingHigh>0.0 && swingLow>0.0) break;
     }
  }

//+------------------------------------------------------------------+
//| Liquidity pools                                                  |
//+------------------------------------------------------------------+
void AddPool(string name,int side,double price,datetime born)
  {
   if(price<=0.0) return;
   for(int i=0;i<ArraySize(pools);i++)
      if(pools[i].name==name && MathAbs(pools[i].price-price)<unitTR*0.05) return;
   int n=ArraySize(pools);
   ArrayResize(pools,n+1);
   pools[n].name=name; pools[n].side=side; pools[n].price=price;
   pools[n].born=born; pools[n].swept=false;
   if(ArraySize(pools)>MAX_POOLS) ArrayRemove(pools,0,ArraySize(pools)-MAX_POOLS);
  }

void BuildPools()
  {
   ArrayFree(pools);

   if(InpUseDayWeek)
     {
      MqlRates d[],w[];
      ArraySetAsSeries(d,true); ArraySetAsSeries(w,true);
      if(CopyRates(_Symbol,PERIOD_D1,0,3,d)>=2)
        {
         AddPool("PDH",DIR_BUY, d[1].high,d[1].time);
         AddPool("PDL",DIR_SELL,d[1].low, d[1].time);
        }
      if(CopyRates(_Symbol,PERIOD_W1,0,3,w)>=2)
        {
         AddPool("PWH",DIR_BUY, w[1].high,w[1].time);
         AddPool("PWL",DIR_SELL,w[1].low, w[1].time);
        }
     }

   if(InpUseAsianRange)
     {
      MqlRates m[];
      ArraySetAsSeries(m,true);
      int cnt=CopyRates(_Symbol,PERIOD_M15,0,400,m);
      if(cnt>20)
        {
         datetime now_u=SrvToUtc(TimeCurrent());
         MqlDateTime nd; TimeToStruct(Shift(now_u,(long)(EuDst(now_u)?3600:0)),nd);
         double ah=-DBL_MAX,al=DBL_MAX;
         datetime at=0;
         for(int i=0;i<cnt;i++)
           {
            datetime u=SrvToUtc(m[i].time);
            MqlDateTime bd; TimeToStruct(Shift(u,(long)(EuDst(u)?3600:0)),bd);
            if(bd.day!=nd.day) break;              // only the current London day
            double lh=bd.hour+bd.min/60.0;
            if(lh>=0.0 && lh<7.0)
              { ah=MathMax(ah,m[i].high); al=MathMin(al,m[i].low); if(at==0) at=m[i].time; }
           }
         if(ah>-DBL_MAX*0.5 && al<DBL_MAX*0.5)
           {
            AddPool("ASIA-H",DIR_BUY, ah,at);
            AddPool("ASIA-L",DIR_SELL,al,at);
           }
        }
     }

   //--- swing pools and equal levels, walked oldest to newest
   double prevH=0,prevL=0;
   int scan=(int)MathMin(bars-pivLen-2,300);
   for(int p=scan;p>=pivLen+1;p--)
     {
      if(IsPivotHigh(p,pivLen))
        {
         if(InpUseEqualLevels && prevH>0.0 && MathAbs(H(p)-prevH)<=unitTR*0.15)
            AddPool("EQH",DIR_BUY,(H(p)+prevH)*0.5,T(p));
         else if(InpUseSwings)
            AddPool("SWING-H",DIR_BUY,H(p),T(p));
         prevH=H(p);
        }
      if(IsPivotLow(p,pivLen))
        {
         if(InpUseEqualLevels && prevL>0.0 && MathAbs(L(p)-prevL)<=unitTR*0.15)
            AddPool("EQL",DIR_SELL,(L(p)+prevL)*0.5,T(p));
         else if(InpUseSwings)
            AddPool("SWING-L",DIR_SELL,L(p),T(p));
         prevL=L(p);
        }
     }

   //--- mark anything price has already taken out. The scan deliberately
   //--- stops at bar 2: bar 1 is the candle DetectRaid() is about to judge,
   //--- and marking it here would pre-empt every raid the EA exists to find.
   for(int i=0;i<ArraySize(pools);i++)
     {
      int from=-1;
      for(int b=0;b<bars;b++) if(T(b)<=pools[i].born){ from=b; break; }
      if(from<2) continue;
      for(int b=from-1;b>=2;b--)
        {
         if(pools[i].side==DIR_BUY  && H(b)>pools[i].price){ pools[i].swept=true; break; }
         if(pools[i].side==DIR_SELL && L(b)<pools[i].price){ pools[i].swept=true; break; }
        }
     }
  }

//+------------------------------------------------------------------+
//| Higher timeframe agreement (optional filter)                     |
//+------------------------------------------------------------------+
int HtfTrend()
  {
   MqlRates h[];
   ArraySetAsSeries(h,true);
   int n=CopyRates(_Symbol,PERIOD_H4,0,300,h);
   if(n<60) return(0);
   int len=3, dir=0;
   double sh=0,sl=0;
   for(int b=n-len-2;b>=1;b--)
     {
      int p=b+len;
      if(p+len<=n-1)
        {
         bool ph=true,pl=true;
         for(int k=1;k<=len;k++)
           {
            if(h[p].high<=h[p-k].high || h[p].high<h[p+k].high) ph=false;
            if(h[p].low >=h[p-k].low  || h[p].low >h[p+k].low ) pl=false;
           }
         if(ph) sh=h[p].high;
         if(pl) sl=h[p].low;
        }
      if(sh>0.0 && h[b].close>sh){ dir= 1; sh=0.0; }
      if(sl>0.0 && h[b].close<sl){ dir=-1; sl=0.0; }
     }
   return(dir);
  }

//+------------------------------------------------------------------+
//| STEP 1 - the raid. A closed candle pierces a pool and closes     |
//| back on the original side, leaving a rejection wick.             |
//+------------------------------------------------------------------+
void DetectRaid()
  {
   if(armed || bars<3) return;

   double hi=H(1),lo=L(1),cl=C(1),op=O(1);
   double rng=MathMax(hi-lo,_Point);

   int    bestIdx=-1, bestDir=0;
   double bestQ=0.0;

   for(int i=0;i<ArraySize(pools);i++)
     {
      if(pools[i].swept) continue;
      double px=pools[i].price;

      //--- sell-side pool taken and reclaimed -> expect a BUY
      if(pools[i].side==DIR_SELL && lo<px && cl>px)
        {
         double wick=(MathMin(cl,op)-lo)/rng;
         if(wick>=InpMinRejection && wick>bestQ){ bestQ=wick; bestIdx=i; bestDir=DIR_BUY; }
        }
      //--- buy-side pool taken and rejected -> expect a SELL
      if(pools[i].side==DIR_BUY && hi>px && cl<px)
        {
         double wick=(hi-MathMax(cl,op))/rng;
         if(wick>=InpMinRejection && wick>bestQ){ bestQ=wick; bestIdx=i; bestDir=DIR_SELL; }
        }
     }
   if(bestIdx<0) return;

   //--- the CHoCH needs a standing level on the opposite side
   double level=(bestDir==DIR_BUY?swingHigh:swingLow);
   if(level<=0.0)
     {
      lastNote=StringFormat("raid on %s ignored - no standing swing %s to break",
                            pools[bestIdx].name,(bestDir==DIR_BUY?"high":"low"));
      return;
     }
   //--- and that level has to be genuinely ahead of price. A level price has
   //--- already passed would be triggered by the next candle regardless of
   //--- what it does, which is not a change of character at all.
   double minGap=0.10*unitTR;
   if((bestDir==DIR_BUY  && level<=cl+minGap) ||
      (bestDir==DIR_SELL && level>=cl-minGap))
     {
      lastNote=StringFormat("raid on %s ignored - the swing %s at %.2f is not ahead of the %.2f close",
                            pools[bestIdx].name,(bestDir==DIR_BUY?"high":"low"),level,cl);
      return;
     }

   pools[bestIdx].swept=true;
   armed=true;
   armDir=bestDir;
   armExtreme=(bestDir==DIR_BUY?lo:hi);
   armCHoCH=level;
   armTime=T(1);
   armBar=0;
   armPool=pools[bestIdx].name;
   armQuality=bestQ;
   nRaids++;

   lastNote=StringFormat("%s raid on %s (rejection %.0f%%) - waiting for a %s CHoCH through %.2f",
                         (bestDir==DIR_BUY?"sell-side":"buy-side"),armPool,bestQ*100.0,
                         (bestDir==DIR_BUY?"bullish":"bearish"),armCHoCH);
   Print("RAID   | ",lastNote);
   if(InpShowSetups)
     {
      string id=PFX+"raid_"+IntegerToString((long)armTime);
      ObjectCreate(0,id,OBJ_ARROW,0,armTime,armExtreme);
      ObjectSetInteger(0,id,OBJPROP_ARROWCODE,armDir==DIR_BUY?233:234);
      ObjectSetInteger(0,id,OBJPROP_COLOR,armDir==DIR_BUY?clrDeepSkyBlue:clrOrange);
      ObjectSetInteger(0,id,OBJPROP_WIDTH,2);
      ObjectSetInteger(0,id,OBJPROP_HIDDEN,true);
      string lid=PFX+"choch_"+IntegerToString((long)armTime);
      datetime lend=(datetime)((long)T(1)+(long)PeriodSeconds()*InpConfirmBars);
      ObjectCreate(0,lid,OBJ_TREND,0,armTime,armCHoCH,lend,armCHoCH);
      ObjectSetInteger(0,lid,OBJPROP_COLOR,clrGold);
      ObjectSetInteger(0,lid,OBJPROP_STYLE,STYLE_DASH);
      ObjectSetInteger(0,lid,OBJPROP_HIDDEN,true);
     }
  }

//+------------------------------------------------------------------+
//| STEP 2 - the change of character. Structure must break the       |
//| standing level within the confirmation window, and the raid      |
//| extreme must hold while it waits.                                |
//+------------------------------------------------------------------+
bool ConfirmCHoCH()
  {
   if(!armed) return(false);
   armBar++;

   //--- the raid low/high failing is the setup being wrong, not late
   if(armDir==DIR_BUY && L(1)<armExtreme)
     {
      lastNote=StringFormat("setup void - price broke back under the %s raid low",armPool);
      Print("VOID   | ",lastNote);
      armed=false; nExpired++;
      return(false);
     }
   if(armDir==DIR_SELL && H(1)>armExtreme)
     {
      lastNote=StringFormat("setup void - price broke back over the %s raid high",armPool);
      Print("VOID   | ",lastNote);
      armed=false; nExpired++;
      return(false);
     }

   if(armBar>InpConfirmBars)
     {
      lastNote=StringFormat("setup expired - no CHoCH within %d bars of the %s raid",InpConfirmBars,armPool);
      Print("EXPIRE | ",lastNote);
      armed=false; nExpired++;
      return(false);
     }

   if(armDir==DIR_BUY  && C(1)>armCHoCH){ nCHoCH++; return(true); }
   if(armDir==DIR_SELL && C(1)<armCHoCH){ nCHoCH++; return(true); }
   return(false);
  }

//+------------------------------------------------------------------+
//| Risk and sizing                                                  |
//+------------------------------------------------------------------+
double TickValueLoss()
  {
   double v=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(v>0.0) return(v);
   return(SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE));
  }
double LossPerLot(double dist)
  {
   double tv=TickValueLoss(), ts=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(tv<=0.0 || ts<=0.0 || dist<=0.0) return(0.0);
   return((dist/ts)*tv);
  }
double LotsFor(double riskMoney,double dist)
  {
   if(InpFixedLots>0.0) return(InpFixedLots);
   double per=LossPerLot(dist);
   if(per<=0.0 || riskMoney<=0.0) return(0.0);

   //--- refuse a degenerate stop rather than sizing an enormous position
   double pt=SymbolInfoDouble(_Symbol,SYMBOL_POINT);
   double lvl=(double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*pt;
   double spr=MathMax(SymbolInfoDouble(_Symbol,SYMBOL_ASK)-SymbolInfoDouble(_Symbol,SYMBOL_BID),0.0);
   double minsl=MathMax(lvl,spr*2.0);
   if(minsl>0.0 && dist<minsl) return(0.0);

   double lots=riskMoney/per;
   double vmin=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double vmax=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double vstep=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(vstep<=0.0) vstep=0.01;
   int vd=VolumeDigits(vstep);
   lots=NormalizeDouble(MathFloor(lots/vstep+1e-9)*vstep,vd);
   if(lots<vmin) return(0.0);
   if(lots>vmax) lots=vmax;
   if(lots<vmin) return(0.0);

   double margin=0.0;
   double price=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   if(OrderCalcMargin(ORDER_TYPE_BUY,_Symbol,lots,price,margin))
     {
      double freeM=AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      while(lots>=vmin && margin>freeM*0.35)
        {
         lots=NormalizeDouble(lots-vstep,vd);
         if(lots<vmin) return(0.0);
         if(!OrderCalcMargin(ORDER_TYPE_BUY,_Symbol,lots,price,margin)) break;
        }
     }
   return(lots);
  }

//+------------------------------------------------------------------+
//| Nearest unswept pool on the far side, as the objective           |
//+------------------------------------------------------------------+
bool FindTarget(int dir,double entry,double minDist,double &tp,string &name)
  {
   bool found=false;
   double best=DBL_MAX;
   for(int i=0;i<ArraySize(pools);i++)
     {
      if(pools[i].swept) continue;
      double px=pools[i].price;
      if(dir==DIR_BUY  && pools[i].side==DIR_BUY  && px>entry+minDist && px-entry<best)
        { best=px-entry; tp=px; name=pools[i].name; found=true; }
      if(dir==DIR_SELL && pools[i].side==DIR_SELL && px<entry-minDist && entry-px<best)
        { best=entry-px; tp=px; name=pools[i].name; found=true; }
     }
   return(found);
  }

//+------------------------------------------------------------------+
//| Position bookkeeping                                             |
//+------------------------------------------------------------------+
bool PositionLive()
  {
   if(posTicket==0) return(false);
   if(!PositionSelectByTicket(posTicket)) return(false);
   if(PositionGetString(POSITION_SYMBOL)!=_Symbol) return(false);
   if((long)PositionGetInteger(POSITION_MAGIC)!=(long)InpMagic) return(false);
   return(true);
  }

int OwnPositions()
  {
   int n=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      if(PositionGetTicket(i)==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=(long)InpMagic) continue;
      n++;
     }
   return(n);
  }

//--- pick up a position that already exists (restart, or a terminal reload)
void AdoptPosition(bool quiet=false)
  {
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong tk=PositionGetTicket(i);
      if(tk==0) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=(long)InpMagic) continue;
      posTicket=tk;
      posId    =(ulong)PositionGetInteger(POSITION_IDENTIFIER);
      posEntry =PositionGetDouble(POSITION_PRICE_OPEN);
      posStop  =PositionGetDouble(POSITION_SL);
      posTP    =PositionGetDouble(POSITION_TP);
      posDir   =(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY?DIR_BUY:DIR_SELL);
      posOpened=(datetime)PositionGetInteger(POSITION_TIME);
      double d =MathAbs(posEntry-posStop);
      posRisk  =(d>0.0?d:(unitTR>0.0?unitTR:1.0));
      donePartial=false; doneBE=false;
      if(!quiet)
        {
         lastNote=StringFormat("adopted an existing %s position at %.2f",
                               (posDir==DIR_BUY?"BUY":"SELL"),posEntry);
         Print("ADOPT  | ",lastNote);
        }
      return;
     }
  }

//--- read what the closed position actually cost or made
void ReportClose()
  {
   double pnl=0.0;
   bool   have=false;
   if(posId!=0 && HistorySelectByPosition(posId))
     {
      int n=HistoryDealsTotal();
      for(int i=0;i<n;i++)
        {
         ulong dt=HistoryDealGetTicket(i);
         if(dt==0) continue;
         long e=(long)HistoryDealGetInteger(dt,DEAL_ENTRY);
         if(e!=DEAL_ENTRY_OUT && e!=DEAL_ENTRY_OUT_BY && e!=DEAL_ENTRY_INOUT) continue;
         pnl+=HistoryDealGetDouble(dt,DEAL_PROFIT)
             +HistoryDealGetDouble(dt,DEAL_SWAP)
             +HistoryDealGetDouble(dt,DEAL_COMMISSION);
         have=true;
        }
     }
   if(have)
      lastNote=StringFormat("position closed: %s%.2f %s",(pnl>=0.0?"+":""),pnl,
                            AccountInfoString(ACCOUNT_CURRENCY));
   else
      lastNote="position closed (result not yet in history)";
   Print("CLOSED | ",lastNote);

   posTicket=0; posId=0; posEntry=0; posStop=0; posTP=0; posRisk=0;
   posDir=0; posOpened=0; donePartial=false; doneBE=false;
   if(InpShowSetups) ObjectsDeleteAll(0,PFX+"live",0,-1);
  }

//+------------------------------------------------------------------+
//| STEP 3 - execution. The CHoCH has just closed; price it, size it |
//| and send it, or say plainly why not.                             |
//+------------------------------------------------------------------+
void TrySignal()
  {
   int    dir   = armDir;
   string pool  = armPool;
   double raidPx= armExtreme;
   double choch = armCHoCH;
   double qual  = armQuality;

   //--- the setup is spent either way: one CHoCH, one decision
   armed=false;

   if(dayBlocked)
     { lastNote="CHoCH confirmed but the daily loss limit has stopped trading"; Print("SKIP   | ",lastNote); return; }
   if(OwnPositions()>=InpMaxPositions)
     { lastNote="CHoCH confirmed but the position limit is already used"; Print("SKIP   | ",lastNote); return; }
   if(InpKillzonesOnly && !InKillzone(TimeCurrent()))
     { lastNote="CHoCH confirmed outside the killzones - not traded"; Print("SKIP   | ",lastNote); return; }
   if(InpRequireHtfAgree)
     {
      int htf=HtfTrend();
      if(htf!=0 && htf!=dir)
        { lastNote="CHoCH confirmed but the H4 trend disagrees"; Print("SKIP   | ",lastNote); return; }
     }

   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   if(ask<=0.0 || bid<=0.0)
     { lastNote="no live quote - entry skipped"; Print("SKIP   | ",lastNote); return; }
   double spread=ask-bid;

   double entry =(dir==DIR_BUY?ask:bid);
   double buffer=0.15*unitTR+spread;
   double stop  =(dir==DIR_BUY?raidPx-buffer:raidPx+buffer);
   double dist  =MathAbs(entry-stop);

   int    dg=(int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   double stops_lvl=(double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*_Point;
   if(dist<=stops_lvl+_Point)
     { lastNote="stop would sit inside the broker's minimum distance"; Print("SKIP   | ",lastNote); return; }
   if(unitTR>0.0 && dist>InpMaxStopUnits*unitTR)
     {
      lastNote=StringFormat("stop is %.1f median candles wide - wider than the %.1f allowed",
                            dist/unitTR,InpMaxStopUnits);
      Print("SKIP   | ",lastNote); return;
     }
   if(spread>dist*InpMaxSpreadPct/100.0)
     {
      lastNote=StringFormat("spread %.2f is %.0f%% of the %.2f stop - too expensive",
                            spread,SafeDiv(spread,dist,0.0)*100.0,dist);
      Print("SKIP   | ",lastNote); return;
     }

   //--- objective: the nearest unswept pool on the far side
   double tp=0.0; string tname="";
   bool   have=FindTarget(dir,entry,dist*InpMinRR,tp,tname);
   if(!have)
     {
      if(InpFallbackRR<=0.0)
        {
         lastNote=StringFormat("no unswept pool beyond %.1fR - no objective, no trade",InpMinRR);
         Print("SKIP   | ",lastNote); return;
        }
      tp=(dir==DIR_BUY?entry+dist*InpFallbackRR:entry-dist*InpFallbackRR);
      tname=StringFormat("measured %.1fR",InpFallbackRR);
     }
   double rr=SafeDiv(MathAbs(tp-entry),dist,0.0);
   if(rr<InpMinRR)
     {
      lastNote=StringFormat("objective %s is only %.2fR away",tname,rr);
      Print("SKIP   | ",lastNote); return;
     }

   //--- size it
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   if(bal<=0.0) bal=AccountInfoDouble(ACCOUNT_EQUITY);
   double riskMoney=bal*InpRiskPercent/100.0;
   double lots=LotsFor(riskMoney,dist);
   if(lots<=0.0)
     {
      lastNote=StringFormat("cannot size a %.2f stop with %.2f of risk on this account",dist,riskMoney);
      Print("SKIP   | ",lastNote); return;
     }

   entry=NormalizeDouble(entry,dg);
   stop =NormalizeDouble(stop,dg);
   tp   =NormalizeDouble(tp,dg);

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippage);
   trade.SetTypeFillingBySymbol(_Symbol);

   bool ok=(dir==DIR_BUY?trade.Buy(lots,_Symbol,0.0,stop,tp,"raid+CHoCH")
                        :trade.Sell(lots,_Symbol,0.0,stop,tp,"raid+CHoCH"));
   if(!ok)
     {
      lastNote=StringFormat("order rejected: %d %s",trade.ResultRetcode(),trade.ResultRetcodeDescription());
      Print("FAIL   | ",lastNote); return;
     }

   posTicket=trade.ResultOrder();
   posDir=dir; posEntry=(trade.ResultPrice()>0.0?trade.ResultPrice():entry);
   posStop=stop; posTP=tp; posRisk=MathAbs(posEntry-stop);
   posOpened=TimeCurrent(); donePartial=false; doneBE=false;
   posId=0;
   if(PositionSelectByTicket(posTicket))
      posId=(ulong)PositionGetInteger(POSITION_IDENTIFIER);
   else
      AdoptPosition(true);
   nTrades++;

   lastNote=StringFormat("%s %.2f lots at %.2f | stop %.2f (%.2f) | target %s %.2f | %.2fR | risk %.2f%%",
                         (dir==DIR_BUY?"BUY":"SELL"),lots,posEntry,posStop,posRisk,tname,posTP,rr,InpRiskPercent);
   Print("ENTRY  | ",lastNote);
   PrintFormat("       | raid on %s, rejection %.0f%%, CHoCH through %.2f, session %s",
               pool,qual*100.0,choch,SessionName(TimeCurrent()));

   if(InpShowSetups)
     {
      string id=PFX+"live_e";
      ObjectCreate(0,id,OBJ_ARROW,0,posOpened,posEntry);
      ObjectSetInteger(0,id,OBJPROP_ARROWCODE,dir==DIR_BUY?225:226);
      ObjectSetInteger(0,id,OBJPROP_COLOR,dir==DIR_BUY?clrLime:clrRed);
      ObjectSetInteger(0,id,OBJPROP_WIDTH,3);
      ObjectSetInteger(0,id,OBJPROP_HIDDEN,true);
     }
  }

//+------------------------------------------------------------------+
//| Management - runs on every tick: partial profit and break even   |
//+------------------------------------------------------------------+
double OpenR()
  {
   if(!PositionLive() || posRisk<=0.0) return(0.0);
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double px =(posDir==DIR_BUY?bid:ask);
   return(SafeDiv(posDir==DIR_BUY?px-posEntry:posEntry-px,posRisk,0.0));
  }

void ManageTick()
  {
   if(!PositionLive()) return;
   double r=OpenR();
   double vol=PositionGetDouble(POSITION_VOLUME);
   double cur=PositionGetDouble(POSITION_SL);
   int    dg =(int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);

   //--- partial profit
   if(InpPartialAtR>0.0 && !donePartial && r>=InpPartialAtR)
     {
      double vstep=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
      double vmin =SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
      if(vstep<=0.0) vstep=0.01;
      int vd=VolumeDigits(vstep);
      double part=NormalizeDouble(MathFloor(vol*Clamp(InpPartialPercent,1.0,95.0)/100.0/vstep+1e-9)*vstep,vd);
      if(part>=vmin && NormalizeDouble(vol-part,vd)>=vmin)
        {
         if(trade.PositionClosePartial(posTicket,part))
           {
            donePartial=true;
            lastNote=StringFormat("took %.2f lots off at +%.2fR",part,r);
            Print("PARTIAL| ",lastNote);
           }
         else
            PrintFormat("PARTIAL| partial close failed: %d %s",trade.ResultRetcode(),trade.ResultRetcodeDescription());
        }
      else
        {
         donePartial=true;                       // nothing left to split, stop retrying
         PrintFormat("PARTIAL| %.2f lots cannot be split at this broker's minimum",vol);
        }
     }

   //--- break even
   if(InpBreakEvenAtR>0.0 && !doneBE && r>=InpBreakEvenAtR)
     {
      double spread=SymbolInfoDouble(_Symbol,SYMBOL_ASK)-SymbolInfoDouble(_Symbol,SYMBOL_BID);
      double be=NormalizeDouble(posDir==DIR_BUY?posEntry+spread+0.05*unitTR
                                              :posEntry-spread-0.05*unitTR,dg);
      bool better=(posDir==DIR_BUY?(cur<=0.0 || be>cur):(cur<=0.0 || be<cur));
      if(better)
        {
         if(trade.PositionModify(posTicket,be,PositionGetDouble(POSITION_TP)))
           {
            doneBE=true; posStop=be;
            lastNote=StringFormat("stop moved to break even at +%.2fR",r);
            Print("BE     | ",lastNote);
           }
         else
            PrintFormat("BE     | stop move failed: %d %s",trade.ResultRetcode(),trade.ResultRetcodeDescription());
        }
      else
         doneBE=true;
     }
  }

//+------------------------------------------------------------------+
//| Management - runs on bar close: structural trail and time stop   |
//+------------------------------------------------------------------+
void ManageBar()
  {
   if(!PositionLive()) return;
   double r=OpenR();
   int    dg=(int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);

   //--- how many closed bars the trade has been alive for
   int held=0;
   for(int b=1;b<bars;b++){ if(T(b)<posOpened) break; held++; }

   //--- time stop: an idea that has gone nowhere is capital sitting still
   if(InpTimeStopBars>0 && held>=InpTimeStopBars && r<0.5)
     {
      if(trade.PositionClose(posTicket))
        {
         lastNote=StringFormat("closed on the time stop after %d bars at %+.2fR",held,r);
         Print("TIME   | ",lastNote);
         return;
        }
     }

   //--- structural trail: follow the swings that are actually holding
   if(InpTrailAfterR>0.0 && r>=InpTrailAfterR)
     {
      double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
      double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      double px =(posDir==DIR_BUY?bid:ask);
      double buffer=0.15*unitTR+(ask-bid);
      double cand=0.0;
      for(int p=pivLen+1;p<(int)MathMin(bars-pivLen-1,120);p++)
        {
         if(posDir==DIR_BUY && IsPivotLow(p,pivLen) && L(p)<px-0.30*unitTR)
           { cand=L(p)-buffer; break; }
         if(posDir==DIR_SELL && IsPivotHigh(p,pivLen) && H(p)>px+0.30*unitTR)
           { cand=H(p)+buffer; break; }
        }
      if(cand>0.0)
        {
         cand=NormalizeDouble(cand,dg);
         double cur=PositionGetDouble(POSITION_SL);
         bool better=(posDir==DIR_BUY?(cur<=0.0 || cand>cur+_Point):(cur<=0.0 || cand<cur-_Point));
         if(better)
           {
            if(trade.PositionModify(posTicket,cand,PositionGetDouble(POSITION_TP)))
              {
               posStop=cand;
               lastNote=StringFormat("trailed the stop to %.2f behind structure at +%.2fR",cand,r);
               Print("TRAIL  | ",lastNote);
              }
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| Daily loss governor                                              |
//+------------------------------------------------------------------+
void RollDay()
  {
   MqlDateTime d; TimeToStruct(TimeCurrent(),d);
   datetime key=MakeUtc(d.year,d.mon,d.day,0);
   if(key!=dayStamp)
     {
      dayStamp=key;
      dayStartEquity=AccountInfoDouble(ACCOUNT_EQUITY);
      if(dayStartEquity<=0.0) dayStartEquity=AccountInfoDouble(ACCOUNT_BALANCE);
      dayBlocked=false;
      PrintFormat("DAY    | new trading day, starting equity %.2f",dayStartEquity);
     }

   if(dayStartEquity>0.0 && !dayBlocked)
     {
      double eq=AccountInfoDouble(ACCOUNT_EQUITY);
      if(eq>0.0)
        {
         double dd=(dayStartEquity-eq)/dayStartEquity*100.0;
         if(dd>=InpMaxDailyLossPct)
           {
            dayBlocked=true;
            lastNote=StringFormat("day stopped: %.2f%% down against a %.2f%% limit",dd,InpMaxDailyLossPct);
            Print("BLOCK  | ",lastNote);
           }
        }
     }
  }

double DayPL()
  {
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   if(dayStartEquity<=0.0 || eq<=0.0) return(0.0);
   return((eq-dayStartEquity)/dayStartEquity*100.0);
  }

//+------------------------------------------------------------------+
//| Chart drawing                                                    |
//+------------------------------------------------------------------+
void DrawPools()
  {
   ObjectsDeleteAll(0,PFX+"pool",0,-1);
   if(!InpShowPools || bars<3) return;

   datetime right=(datetime)((long)T(0)+(long)PeriodSeconds()*12);
   for(int i=0;i<ArraySize(pools);i++)
     {
      datetime from=pools[i].born;
      if(from<=0 || from>T(0)) from=T(bars>60?60:bars-1);
      string id=PFX+"pool_"+IntegerToString(i);
      if(!ObjectCreate(0,id,OBJ_TREND,0,from,pools[i].price,right,pools[i].price)) continue;
      color c=(pools[i].swept?clrDimGray:(pools[i].side==DIR_BUY?clrIndianRed:clrSteelBlue));
      ObjectSetInteger(0,id,OBJPROP_COLOR,c);
      ObjectSetInteger(0,id,OBJPROP_STYLE,pools[i].swept?STYLE_DOT:STYLE_SOLID);
      ObjectSetInteger(0,id,OBJPROP_WIDTH,1);
      ObjectSetInteger(0,id,OBJPROP_RAY_RIGHT,false);
      ObjectSetInteger(0,id,OBJPROP_BACK,true);
      ObjectSetInteger(0,id,OBJPROP_HIDDEN,true);
      ObjectSetInteger(0,id,OBJPROP_SELECTABLE,false);

      string tid=PFX+"poolt_"+IntegerToString(i);
      if(ObjectCreate(0,tid,OBJ_TEXT,0,right,pools[i].price))
        {
         ObjectSetString(0,tid,OBJPROP_TEXT," "+pools[i].name+(pools[i].swept?" (swept)":""));
         ObjectSetInteger(0,tid,OBJPROP_COLOR,c);
         ObjectSetInteger(0,tid,OBJPROP_FONTSIZE,7);
         ObjectSetInteger(0,tid,OBJPROP_ANCHOR,ANCHOR_LEFT);
         ObjectSetInteger(0,tid,OBJPROP_HIDDEN,true);
         ObjectSetInteger(0,tid,OBJPROP_SELECTABLE,false);
        }
     }
  }

//--- raid and CHoCH marks are history, not forecasts: they are never
//--- moved once drawn, only dropped when they scroll out of the data
void PruneMarks()
  {
   if(bars<10) return;
   datetime cut=T(bars-1);
   int total=ObjectsTotal(0,0,-1);
   for(int i=total-1;i>=0;i--)
     {
      string nm=ObjectName(0,i,0,-1);
      if(StringFind(nm,PFX+"raid_")!=0 && StringFind(nm,PFX+"choch_")!=0) continue;
      if((datetime)ObjectGetInteger(0,nm,OBJPROP_TIME,0)<cut) ObjectDelete(0,nm);
     }
  }

//+------------------------------------------------------------------+
//| Status panel                                                     |
//+------------------------------------------------------------------+
string Pad(string s,int n)
  {
   while(StringLen(s)<n) s=s+" ";
   return(s);
  }
string Rule(int n)
  {
   string s="";
   for(int i=0;i<n;i++) s=s+"-";
   return(s);
  }
void PanelRow(string &rows[],color &cl[],int &n,string text,color c)
  {
   ArrayResize(rows,n+1); ArrayResize(cl,n+1);
   rows[n]=text; cl[n]=c; n++;
  }
string KV(string k,string v){ return(Pad(k,17)+": "+v); }

void DrawPanel()
  {
   ObjectsDeleteAll(0,PFX+"P_",0,-1);
   if(!InpShowPanel) return;

   const int COLS=52;
   string rows[]; color cl[]; int n=0;

   PanelRow(rows,cl,n,"SMC LIQUIDITY RAID + CHoCH   "+_Symbol+" "+EnumToString((ENUM_TIMEFRAMES)Period()),clrGold);
   PanelRow(rows,cl,n,Rule(COLS),clrDimGray);

   PanelRow(rows,cl,n,KV("Server time",TimeToString(TimeCurrent(),TIME_DATE|TIME_MINUTES)
            +StringFormat("  (GMT%+d)",gmtOffset)),clrWhite);
   PanelRow(rows,cl,n,KV("Session",SessionName(TimeCurrent())
            +(InpKillzonesOnly?(InKillzone(TimeCurrent())?"  [tradeable]":"  [waiting]"):"")),clrWhite);

   string mode;
   if(dayBlocked)               mode="DAY STOPPED - no new trades";
   else if(PositionLive())      mode="IN A TRADE";
   else if(armed)               mode="SETUP ARMED - waiting for the CHoCH";
   else                         mode="HUNTING - waiting for a liquidity raid";
   PanelRow(rows,cl,n,KV("State",mode),dayBlocked?clrTomato:clrAqua);
   PanelRow(rows,cl,n,Rule(COLS),clrDimGray);

   //--- what the EA is reading off the chart
   string trend=(trendDir==DIR_BUY?"bullish":(trendDir==DIR_SELL?"bearish":"undecided"));
   PanelRow(rows,cl,n,KV("Structure",trend),
            trendDir==DIR_BUY?clrLime:(trendDir==DIR_SELL?clrTomato:clrSilver));
   PanelRow(rows,cl,n,KV("Standing swings",StringFormat("high %s / low %s",
            (swingHigh>0.0?DoubleToString(swingHigh,2):"none"),
            (swingLow >0.0?DoubleToString(swingLow, 2):"none"))),clrWhite);
   PanelRow(rows,cl,n,KV("One candle",StringFormat("%.2f  (median true range, %d bars)",unitTR,
            (int)MathMin(CAL_BARS,MathMax(bars-2,0)))),clrWhite);
   PanelRow(rows,cl,n,KV("Pivot length",StringFormat("%d  (%s)",pivLen,
            InpPivotLen>=2?"fixed":"adapted to this market")),clrWhite);

   int live=0,swept=0;
   for(int i=0;i<ArraySize(pools);i++){ if(pools[i].swept) swept++; else live++; }
   PanelRow(rows,cl,n,KV("Liquidity pools",StringFormat("%d unswept / %d already taken",live,swept)),clrWhite);

   double sp=SymbolInfoDouble(_Symbol,SYMBOL_ASK)-SymbolInfoDouble(_Symbol,SYMBOL_BID);
   PanelRow(rows,cl,n,KV("Spread",StringFormat("%.2f  (%.0f%% of one candle)",sp,
            SafeDiv(sp,unitTR,0.0)*100.0)),
            (unitTR>0.0 && sp>0.25*unitTR)?clrOrange:clrWhite);
   PanelRow(rows,cl,n,Rule(COLS),clrDimGray);

   //--- the armed setup
   if(armed)
     {
      PanelRow(rows,cl,n,KV("Armed setup",StringFormat("%s after the %s raid",
               (armDir==DIR_BUY?"BUY":"SELL"),armPool)),armDir==DIR_BUY?clrLime:clrTomato);
      PanelRow(rows,cl,n,KV("Rejection wick",StringFormat("%.0f%% of the raid candle",armQuality*100.0)),clrWhite);
      PanelRow(rows,cl,n,KV("Must hold",StringFormat("%.2f  (the raid %s)",armExtreme,
               (armDir==DIR_BUY?"low":"high"))),clrWhite);
      PanelRow(rows,cl,n,KV("CHoCH level",StringFormat("%.2f  (close through it to trigger)",armCHoCH)),clrGold);
      PanelRow(rows,cl,n,KV("Window",StringFormat("bar %d of %d",armBar,InpConfirmBars)),clrWhite);
     }
   else
      PanelRow(rows,cl,n,KV("Armed setup","none - no pool has been raided and reclaimed"),clrSilver);
   PanelRow(rows,cl,n,Rule(COLS),clrDimGray);

   //--- the open position
   if(PositionLive())
     {
      double r=OpenR();
      PanelRow(rows,cl,n,KV("Position",StringFormat("%s %.2f lots from %.2f",
               (posDir==DIR_BUY?"BUY":"SELL"),PositionGetDouble(POSITION_VOLUME),posEntry)),
               posDir==DIR_BUY?clrLime:clrTomato);
      PanelRow(rows,cl,n,KV("Stop / target",StringFormat("%.2f / %.2f  (1R = %.2f)",
               PositionGetDouble(POSITION_SL),PositionGetDouble(POSITION_TP),posRisk)),clrWhite);
      PanelRow(rows,cl,n,KV("Open result",StringFormat("%+.2fR   %+.2f %s",r,
               PositionGetDouble(POSITION_PROFIT),AccountInfoString(ACCOUNT_CURRENCY))),
               r>=0.0?clrLime:clrTomato);
      PanelRow(rows,cl,n,KV("Done",StringFormat("partial %s | break even %s",
               (donePartial?"yes":"no"),(doneBE?"yes":"no"))),clrSilver);
     }
   else
      PanelRow(rows,cl,n,KV("Position","flat"),clrSilver);
   PanelRow(rows,cl,n,Rule(COLS),clrDimGray);

   //--- account and tally
   PanelRow(rows,cl,n,KV("Account",StringFormat("balance %.2f | equity %.2f %s",
            AccountInfoDouble(ACCOUNT_BALANCE),AccountInfoDouble(ACCOUNT_EQUITY),
            AccountInfoString(ACCOUNT_CURRENCY))),clrWhite);
   double dpl=DayPL();
   PanelRow(rows,cl,n,KV("Day",StringFormat("%+.2f%%   (stops at -%.2f%%)",dpl,InpMaxDailyLossPct)),
            dpl>=0.0?clrLime:(dpl<=-InpMaxDailyLossPct*0.6?clrOrange:clrTomato));
   PanelRow(rows,cl,n,KV("Risk per trade",StringFormat("%.2f%% of balance",InpRiskPercent)),clrWhite);
   PanelRow(rows,cl,n,KV("Tally",StringFormat("%d raids | %d CHoCH | %d trades | %d unused",
            nRaids,nCHoCH,nTrades,nExpired)),clrWhite);
   PanelRow(rows,cl,n,Rule(COLS),clrDimGray);

   string note=lastNote;
   if(StringLen(note)>COLS-19) note=StringSubstr(note,0,COLS-22)+"...";
   PanelRow(rows,cl,n,KV("Last decision",note),clrYellow);

   //--- measure the font the way the chart will actually render it:
   //--- a negative size is DPI aware, a positive one is not
   TextSetFont("Courier New",-InpPanelFontSize*10,0,0);
   uint tw=0,th=0;
   TextGetSize("MMMMMMMMMMMMMMMMMMMM",tw,th);
   int charW=(int)MathCeil((double)tw/20.0);
   if(charW<5) charW=(int)MathMax(5.0,InpPanelFontSize*0.62);
   int rowH=(int)MathMax((double)th+4.0,InpPanelFontSize*1.7);

   int padX=8,padY=6;
   int width =charW*COLS+padX*2;
   int height=rowH*n+padY*2;

   //--- the background must exist before the labels: on an MT5 chart the
   //--- creation order is the paint order
   string bg=PFX+"P_bg";
   ObjectCreate(0,bg,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(0,bg,OBJPROP_CORNER,CORNER_LEFT_UPPER);
   ObjectSetInteger(0,bg,OBJPROP_XDISTANCE,8);
   ObjectSetInteger(0,bg,OBJPROP_YDISTANCE,18);
   ObjectSetInteger(0,bg,OBJPROP_XSIZE,width);
   ObjectSetInteger(0,bg,OBJPROP_YSIZE,height);
   ObjectSetInteger(0,bg,OBJPROP_BGCOLOR,C'18,20,26');
   ObjectSetInteger(0,bg,OBJPROP_BORDER_TYPE,BORDER_FLAT);
   ObjectSetInteger(0,bg,OBJPROP_COLOR,clrDimGray);
   ObjectSetInteger(0,bg,OBJPROP_WIDTH,1);
   ObjectSetInteger(0,bg,OBJPROP_BACK,false);
   ObjectSetInteger(0,bg,OBJPROP_HIDDEN,true);
   ObjectSetInteger(0,bg,OBJPROP_SELECTABLE,false);

   for(int i=0;i<n;i++)
     {
      string id=PFX+"P_r"+IntegerToString(i);
      ObjectCreate(0,id,OBJ_LABEL,0,0,0);
      ObjectSetInteger(0,id,OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetInteger(0,id,OBJPROP_XDISTANCE,8+padX);
      ObjectSetInteger(0,id,OBJPROP_YDISTANCE,18+padY+rowH*i);
      ObjectSetString (0,id,OBJPROP_TEXT,rows[i]);
      ObjectSetString (0,id,OBJPROP_FONT,"Courier New");
      ObjectSetInteger(0,id,OBJPROP_FONTSIZE,InpPanelFontSize);
      ObjectSetInteger(0,id,OBJPROP_COLOR,cl[i]);
      ObjectSetInteger(0,id,OBJPROP_ANCHOR,ANCHOR_LEFT_UPPER);
      ObjectSetInteger(0,id,OBJPROP_BACK,false);
      ObjectSetInteger(0,id,OBJPROP_HIDDEN,true);
      ObjectSetInteger(0,id,OBJPROP_SELECTABLE,false);
     }
  }

//+------------------------------------------------------------------+
//| Console readout - one line per closed bar, so the log is a       |
//| record of what the EA saw and not just what it did               |
//+------------------------------------------------------------------+
void LogBar()
  {
   int live=0;
   for(int i=0;i<ArraySize(pools);i++) if(!pools[i].swept) live++;
   string state;
   if(PositionLive())   state=StringFormat("in a %s at %+.2fR",(posDir==DIR_BUY?"BUY":"SELL"),OpenR());
   else if(armed)       state=StringFormat("armed %s on %s, bar %d/%d, needs a close %s %.2f",
                                (armDir==DIR_BUY?"BUY":"SELL"),armPool,armBar,InpConfirmBars,
                                (armDir==DIR_BUY?"above":"below"),armCHoCH);
   else                 state="hunting";
   PrintFormat("BAR    | %s C=%.2f | %s | 1 candle %.2f | swing H %.2f L %.2f | %d pools live | %s%s",
               TimeToString(T(1),TIME_DATE|TIME_MINUTES),C(1),
               (trendDir==DIR_BUY?"structure bullish":(trendDir==DIR_SELL?"structure bearish":"structure undecided")),
               unitTR,swingHigh,swingLow,live,state,
               (dayBlocked?" | DAY STOPPED":""));
  }

//+------------------------------------------------------------------+
//| Broker clock offset - re-read, never cached from init alone      |
//+------------------------------------------------------------------+
int DetectGmt()
  {
   datetime srv=TimeTradeServer();
   if(srv<=0) srv=TimeCurrent();
   datetime utc=TimeGMT();
   if(srv<=0 || utc<=0) return(gmtOffset);
   return((int)MathRound((double)((long)srv-(long)utc)/3600.0));
  }

//--- declared here because OnBarClose() below calls it
void LogCHoCH();

//+------------------------------------------------------------------+
//| One closed bar: read the chart, then decide                      |
//+------------------------------------------------------------------+
void OnBarClose()
  {
   if(!Refresh())
     {
      lastNote="waiting for enough chart history to calibrate";
      return;
     }
   gmtOffset=DetectGmt();

   MapStructure();
   BuildPools();
   RollDay();
   ManageBar();

   bool acted=false;
   if(armed)
     {
      if(ConfirmCHoCH())
        {
         LogCHoCH();
         TrySignal();
         acted=true;
        }
     }
   if(!armed && !acted) DetectRaid();

   DrawPools();
   PruneMarks();
   LogBar();
  }

void LogCHoCH()
  {
   PrintFormat("CHoCH  | %s change of character confirmed - close %.2f broke %.2f (raid on %s)",
               (armDir==DIR_BUY?"bullish":"bearish"),C(1),armCHoCH,armPool);
  }

//+------------------------------------------------------------------+
//| Lifecycle                                                        |
//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpConfirmBars<1)
     { Print("INIT   | the confirmation window must be at least 1 bar"); return(INIT_PARAMETERS_INCORRECT); }
   if(InpRiskPercent<=0.0 && InpFixedLots<=0.0)
     { Print("INIT   | set either a risk percent or a fixed lot size"); return(INIT_PARAMETERS_INCORRECT); }
   if(InpMinRR<0.5)
     { Print("INIT   | a minimum reward:risk below 0.5 is not worth trading"); return(INIT_PARAMETERS_INCORRECT); }

   ObjectsDeleteAll(0,PFX,0,-1);

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippage);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetAsyncMode(false);
   trade.LogLevel(LOG_LEVEL_ERRORS);

   gmtOffset=DetectGmt();

   Print("=====================================================================");
   Print("SMC LIQUIDITY RAID + CHoCH  |  ",_Symbol," ",EnumToString((ENUM_TIMEFRAMES)Period()));
   Print("  BUY : sell-side pool raided and reclaimed, then a close above the");
   Print("        swing high that was standing at the raid. Stop under the raid.");
   Print("  SELL: the exact mirror.");
   PrintFormat("  Broker clock GMT%+d | confirmation window %d bars | min R:R %.2f",
               gmtOffset,InpConfirmBars,InpMinRR);
   PrintFormat("  Risk %.2f%% per trade | day stops at -%.2f%% | max %d position(s)",
               InpRiskPercent,InpMaxDailyLossPct,InpMaxPositions);
   if(StringFind(_Symbol,"XAU")<0)
      PrintFormat("  NOTE: this EA was built for XAUUSD; %s will still be traded by the same rules.",_Symbol);
   if(Period()!=PERIOD_M15)
     {
      Print("  NOTE: M15 is the intended timeframe. The rules themselves are");
      Print("        timeframe agnostic, but the confirmation window, stop width");
      Print("        and pool set were chosen with M15 gold in mind.");
     }
   Print("=====================================================================");

   if(Refresh())
     {
      MapStructure();
      BuildPools();
      DrawPools();
     }
   AdoptPosition();
   RollDay();
   lastNote="initialised - hunting for a liquidity raid";
   DrawPanel();
   ChartRedraw();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   ObjectsDeleteAll(0,PFX,0,-1);
   ChartRedraw();
   PrintFormat("DEINIT | stopped (reason %d) | %d raids, %d CHoCH, %d trades, %d unused setups",
               reason,nRaids,nCHoCH,nTrades,nExpired);
  }

datetime g_lastBar=0;
uint     g_lastPaint=0;

void OnTick()
  {
   //--- a position that has gone needs its result read before anything else
   if(posTicket!=0 && !PositionLive()) ReportClose();

   ManageTick();

   datetime t0=(datetime)iTime(_Symbol,PERIOD_CURRENT,0);
   if(t0>0 && t0!=g_lastBar)
     {
      g_lastBar=t0;
      OnBarClose();
      g_lastPaint=0;                                   // force a repaint on the new bar
     }

   uint now=GetTickCount();
   if(g_lastPaint==0 || now-g_lastPaint>900)
     {
      g_lastPaint=now;
      DrawPanel();
      ChartRedraw();
     }
  }
