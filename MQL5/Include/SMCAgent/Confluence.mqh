//+------------------------------------------------------------------+
//|                                                   Confluence.mqh |
//|                                                                  |
//|  The agent's reasoning layer.                                    |
//|                                                                  |
//|  On every closed bar it reads the chart through the SMC engines   |
//|  (entry / intermediate / higher timeframe), proposes a directional|
//|  hypothesis from one of three researched playbooks, and then      |
//|  measures 17 confluence factors for that hypothesis. Every factor |
//|  is a measurement of the live tape, normalised to -1..+1, never a |
//|  fixed technical trigger. The factors are handed to the online    |
//|  model which returns a probability of the setup working.          |
//|                                                                  |
//|  Playbooks (from the research notes in docs/RESEARCH.md):         |
//|    A  Liquidity raid -> CHoCH -> inducement run -> discount or    |
//|       premium OB / FVG (ICT "turtle soup" style reversal)          |
//|    B  Post-release raid: the same shape immediately after a high  |
//|       impact macro print, when the sweep is engineered by the news|
//|    C  Trend continuation: BOS in the HTF direction, retrace into  |
//|       the fresh order block / imbalance that produced it          |
//+------------------------------------------------------------------+
#ifndef __SMC_CONFLUENCE_MQH__
#define __SMC_CONFLUENCE_MQH__

#include "Defs.mqh"
#include "MarketState.mqh"
#include "SmcEngine.mqh"
#include "NewsFilter.mqh"
#include "Learner.mqh"
#include "Logger.mqh"

//--- feature vector layout ------------------------------------------
#define F_HTF_BIAS      0
#define F_MID_BIAS      1
#define F_STRUCTURE     2
#define F_SWEEP         3
#define F_OB_QUALITY    4
#define F_FVG_CONF      5
#define F_PREM_DISC     6
#define F_DISPLACEMENT  7
#define F_SESSION       8
#define F_VOLATILITY    9
#define F_EXECUTION    10
#define F_RR           11
#define F_KEYLEVEL     12
#define F_CANDLE       13
#define F_VOLUME       14
#define F_NEWS         15
#define F_INDUCEMENT   16
#define F_COUNT        17

class CConfluence
  {
private:
   CMarketState     *m_ms;
   CSmcEngine       *m_e;      // entry timeframe
   CSmcEngine       *m_m;      // intermediate timeframe
   CSmcEngine       *m_h;      // higher timeframe
   CNewsFilter      *m_news;
   COnlineLearner   *m_model;
   CLogger          *m_log;

   int               m_gmt;
   int               m_news_block_before;
   int               m_news_block_after;
   int               m_news_importance;

   SFactor           m_f[];
   double            m_x[];
   string            m_veto;
   string            m_context;
   int               m_bias_htf;
   int               m_bias_mid;
   string            m_playbook;

   //--- key levels of the day / week ---------------------------------
   double            m_pdh,m_pdl,m_pwh,m_pwl,m_ah,m_al;
   bool              m_has_day,m_has_week,m_has_asia;

   void              SetFactor(const int idx,const string name,const double raw,const double score,const string note)
     {
      if(idx<0 || idx>=F_COUNT) return;
      m_f[idx].name=name;
      m_f[idx].raw=raw;
      m_f[idx].score=SmcClamp(score,-1.0,1.0);
      m_f[idx].weight=(m_model!=NULL?m_model.Weight(idx):0.0);
      m_f[idx].contrib=m_f[idx].score*m_f[idx].weight;
      m_f[idx].note=note;
      m_f[idx].veto=false;
      m_x[idx]=m_f[idx].score;
     }

   double            Orient(const double bullish_score,const int dir)
     { return(dir==DIR_BEAR?-bullish_score:bullish_score); }

   //--- session / killzone quality for gold ---------------------------
   double            SessionScore(const datetime t,string &label)
     {
      double gh=SmcGmtHourF(t,m_gmt);
      int dow=SmcDayOfWeek(t);
      double s=0.0;
      if(gh>=7.0 && gh<10.0)        { s= 1.00; label="London killzone"; }
      else if(gh>=12.0 && gh<15.0)  { s= 1.00; label="New York killzone / London overlap"; }
      else if(gh>=10.0 && gh<12.0)  { s= 0.30; label="London late morning"; }
      else if(gh>=15.0 && gh<17.0)  { s= 0.35; label="New York afternoon"; }
      else if(gh>=0.0  && gh<7.0)   { s=-0.35; label="Asian accumulation"; }
      else                          { s=-0.70; label="illiquid late session"; }
      if(dow==5 && gh>=15.0) { s=MathMin(s,-0.60); label="Friday close - liquidity draining"; }
      if(dow==1 && gh<6.0)   { s=MathMin(s, 0.00); label="Monday pre-London"; }
      if(dow==0 || dow==6)   { s=-1.00; label="weekend"; }
      return(s);
     }

   void              LoadKeyLevels(void)
     {
      m_has_day =m_ms.PrevDayLevels(m_pdh,m_pdl);
      m_has_week=m_ms.PrevWeekLevels(m_pwh,m_pwl);
      m_has_asia=m_ms.AsianRange(m_gmt,m_ah,m_al);
     }

   //--- push the external pools into the entry engine ------------------
   void              FeedExternalLiquidity(void)
     {
      datetime now=SmcNow();
      if(m_has_day)
        {
         m_e.AddLiquidity(LQ_PDH,DIR_BULL,m_pdh,now-86400,1.00);
         m_e.AddLiquidity(LQ_PDL,DIR_BEAR,m_pdl,now-86400,1.00);
        }
      if(m_has_week)
        {
         m_e.AddLiquidity(LQ_PWH,DIR_BULL,m_pwh,now-7*86400,0.95);
         m_e.AddLiquidity(LQ_PWL,DIR_BEAR,m_pwl,now-7*86400,0.95);
        }
      if(m_has_asia)
        {
         m_e.AddLiquidity(LQ_ASIA_H,DIR_BULL,m_ah,SmcDayStart(now),0.90);
         m_e.AddLiquidity(LQ_ASIA_L,DIR_BEAR,m_al,SmcDayStart(now),0.90);
        }
      m_e.RefreshSweeps();
     }

   double            NearestKeyLevelDistance(const double price,string &name)
     {
      double best=DBL_MAX;
      name="";
      if(m_has_day)
        {
         if(MathAbs(price-m_pdh)<best) { best=MathAbs(price-m_pdh); name="PDH"; }
         if(MathAbs(price-m_pdl)<best) { best=MathAbs(price-m_pdl); name="PDL"; }
        }
      if(m_has_week)
        {
         if(MathAbs(price-m_pwh)<best) { best=MathAbs(price-m_pwh); name="PWH"; }
         if(MathAbs(price-m_pwl)<best) { best=MathAbs(price-m_pwl); name="PWL"; }
        }
      if(m_has_asia)
        {
         if(MathAbs(price-m_ah)<best) { best=MathAbs(price-m_ah); name="ASIA-H"; }
         if(MathAbs(price-m_al)<best) { best=MathAbs(price-m_al); name="ASIA-L"; }
        }
      return(best==DBL_MAX?-1.0:best);
     }

   //--- directional read of a higher timeframe engine -------------------
   int               EngineBias(CSmcEngine *eng,double &conviction)
     {
      conviction=0.0;
      if(eng==NULL) return(DIR_NONE);
      int t=eng.Trend();
      if(t==DIR_NONE) { t=eng.InternalTrend(); conviction=0.35; }
      else conviction=0.75;
      //--- a fresh CHoCH against the trend lowers conviction
      if(eng.LastChochTime()>0 && eng.LastChochDir()!=t && eng.LastChochTime()>eng.LastBosTime())
        { conviction*=0.45; t=eng.LastChochDir(); }
      //--- position inside the dealing range refines it
      double hi,lo;
      if(eng.Range(hi,lo))
        {
         double pos=eng.RangePosition(SymbolInfoDouble(m_ms.Symbol(),SYMBOL_BID));
         if(t==DIR_BULL && pos>0.85) conviction*=0.6;   // buying at the top of the range
         if(t==DIR_BEAR && pos<0.15) conviction*=0.6;
        }
      return(t);
     }

public:
                     CConfluence(void): m_ms(NULL), m_e(NULL), m_m(NULL), m_h(NULL), m_news(NULL),
                                        m_model(NULL), m_log(NULL), m_gmt(0), m_news_block_before(15),
                                        m_news_block_after(10), m_news_importance(3), m_veto(""), m_context(""),
                                        m_bias_htf(DIR_NONE), m_bias_mid(DIR_NONE), m_playbook(""),
                                        m_pdh(0), m_pdl(0), m_pwh(0), m_pwl(0), m_ah(0), m_al(0),
                                        m_has_day(false), m_has_week(false), m_has_asia(false)
     {
      ArrayResize(m_f,F_COUNT);
      ArrayResize(m_x,F_COUNT);
      ArrayInitialize(m_x,0.0);
     }

   void              Init(CMarketState *ms,CSmcEngine *entry,CSmcEngine *mid,CSmcEngine *high,
                          CNewsFilter *news,COnlineLearner *model,CLogger *log,const int gmt_offset,
                          const int news_before,const int news_after,const int news_importance)
     {
      m_ms=ms; m_e=entry; m_m=mid; m_h=high; m_news=news; m_model=model; m_log=log;
      m_gmt=gmt_offset;
      m_news_block_before=news_before;
      m_news_block_after=news_after;
      m_news_importance=news_importance;
     }

   void              SetGmtOffset(const int gmt_offset) { m_gmt=gmt_offset; }
   int               GmtOffset(void) const { return(m_gmt); }

   //--- accessors for the dashboard -------------------------------------
   int               FactorCount(void) { return(F_COUNT); }
   bool              GetFactor(const int i,SFactor &f)
     { if(i<0 || i>=F_COUNT) return(false); f=m_f[i]; return(true); }
   void              GetVector(double &dst[])
     { ArrayResize(dst,F_COUNT); for(int i=0;i<F_COUNT;i++) dst[i]=m_x[i]; }
   string            Veto(void)    const { return(m_veto);    }
   string            Context(void) const { return(m_context); }
   int               BiasHtf(void) const { return(m_bias_htf); }
   int               BiasMid(void) const { return(m_bias_mid); }
   string            Playbook(void)const { return(m_playbook); }
   bool              HasDayLevels(void) const { return(m_has_day); }
   double            PDH(void) const { return(m_pdh); }
   double            PDL(void) const { return(m_pdl); }
   double            PWH(void) const { return(m_pwh); }
   double            PWL(void) const { return(m_pwl); }
   bool              HasAsia(void) const { return(m_has_asia); }
   double            AsiaHigh(void) const { return(m_ah); }
   double            AsiaLow(void)  const { return(m_al); }

   //+---------------------------------------------------------------+
   //| Main evaluation, called once per closed bar                    |
   //+---------------------------------------------------------------+
   bool              Evaluate(SSignal &sig)
     {
      sig.valid=false;
      sig.dir=DIR_NONE;
      sig.rationale="";
      sig.model="";
      m_veto="";
      m_playbook="none";
      ArrayInitialize(m_x,0.0);

      if(m_ms==NULL || m_e==NULL) { m_veto="engines not ready"; return(false); }

      LoadKeyLevels();
      FeedExternalLiquidity();

      double unit=m_e.Unit();
      if(unit<=0.0) { m_veto="calibration not ready"; return(false); }

      double bid=SymbolInfoDouble(m_ms.Symbol(),SYMBOL_BID);
      double ask=SymbolInfoDouble(m_ms.Symbol(),SYMBOL_ASK);
      double close1=m_ms.EClose(1);
      datetime bt=m_ms.ETime(1);

      double conv_h=0.0,conv_m=0.0;
      m_bias_htf=EngineBias(m_h,conv_h);
      m_bias_mid=EngineBias(m_m,conv_m);

      //--- directional hypothesis ------------------------------------
      int dir=DIR_NONE;
      string why="";
      bool post_news=false;

      SNewsEvent ne;
      ne.time=0; ne.name=""; ne.currency=""; ne.importance=0;
      if(m_news!=NULL && m_news.JustReleased(SmcNow(),60,m_news_importance,ne)) post_news=true;

      //--- playbook A / B : liquidity raid then change of character
      if(m_e.SweepValid() && m_e.SweepDir()!=DIR_NONE)
        {
         int d=m_e.SweepDir();
         bool choch_ok=(m_e.LastChochDir()==d && m_e.LastChochTime()>=m_e.SweepTime());
         bool bos_ok  =(m_e.LastBosDir()==d   && m_e.LastBosTime()  >=m_e.SweepTime());
         bool internal_ok=(m_e.InternalTrend()==d);
         if(choch_ok || bos_ok || internal_ok)
           {
            dir=d;
            m_playbook=(post_news?"B - post-release liquidity raid":"A - liquidity raid + CHoCH");
            why=StringFormat("%s liquidity taken at %s then structure shifted %s",
                             (d==DIR_BULL?"sell-side":"buy-side"),m_e.SweepPool(),SmcDirStr(d));
           }
        }
      //--- playbook C : continuation into the origin of the last break
      if(dir==DIR_NONE)
        {
         int d=m_e.Trend();
         if(d!=DIR_NONE && d==m_bias_htf && m_e.LastBosDir()==d && m_e.LastBosTime()>=m_e.LastChochTime())
           {
            SZone probe;
            double reach=unit*0.6;
            if(m_e.FindActiveZone(d,close1,reach,probe))
              {
               dir=d;
               m_playbook="C - trend continuation into origin";
               why=StringFormat("%s BOS with higher timeframe agreement, price back inside the %s that caused it",
                                SmcDirStr(d),SmcZoneStr(probe.kind));
              }
           }
        }

      if(dir==DIR_NONE)
        {
         m_context=StringFormat("HTF %s / MID %s / entry %s - no raid or continuation trigger on this close",
                                SmcDirStr(m_bias_htf),SmcDirStr(m_bias_mid),SmcDirStr(m_e.Trend()));
         BuildContextFactors(dir);
         return(false);
        }

      //--- the zone we intend to trade from --------------------------
      SZone zone;
      ZeroMemory(zone);
      bool have_zone=m_e.FindActiveZone(dir,close1,unit*0.75,zone);
      if(!have_zone)
        {
         //--- accept the sweep candle itself as the point of interest
         zone.kind=ZONE_OB;
         zone.dir=dir;
         if(dir==DIR_BULL) { zone.bottom=m_e.SweepExtreme(); zone.top=m_e.SweepExtreme()+unit*0.6; }
         else              { zone.top=m_e.SweepExtreme();    zone.bottom=m_e.SweepExtreme()-unit*0.6; }
         zone.t_from=m_e.SweepTime();
         zone.t_active=bt;
         zone.t_to=bt;
         zone.strength=0.45;
         zone.displacement=1.0;
         zone.has_fvg=false;
         zone.vol_ratio=1.0;
         zone.mitigated=false;
         zone.broken=false;
         zone.uid=0;
        }

      //--- entry, protective stop and objectives ----------------------
      double entry=(dir==DIR_BULL?ask:bid);
      double buffer=unit*0.35+m_ms.SpreadPrice()*2.0;
      double sl;
      if(dir==DIR_BULL)
        {
         sl=MathMin(zone.bottom,(m_e.SweepValid() && m_e.SweepDir()==DIR_BULL?m_e.SweepExtreme():zone.bottom))-buffer;
         sl=MathMin(sl,m_ms.ELow(1)-buffer);
         //--- inducement that has not been run yet is resting liquidity:
         //--- the invalidation has to sit beyond it, never in front of it
         if(zone.idm>0.0 && !zone.idm_taken) sl=MathMin(sl,zone.idm-buffer);
        }
      else
        {
         sl=MathMax(zone.top,(m_e.SweepValid() && m_e.SweepDir()==DIR_BEAR?m_e.SweepExtreme():zone.top))+buffer;
         sl=MathMax(sl,m_ms.EHigh(1)+buffer);
         if(zone.idm>0.0 && !zone.idm_taken) sl=MathMax(sl,zone.idm+buffer);
        }
      double risk=MathAbs(entry-sl);
      if(risk<=0.0)
        {
         m_veto="degenerate stop distance";
         m_context=StringFormat("%s %s - %s, but %s",SmcDirShort(dir),m_playbook,why,m_veto);
         BuildContextFactors(dir);
         return(false);
        }

      //--- the stop must stay inside what this tape normally does -----
      double max_risk=unit*4.5;
      if(risk>max_risk)
        {
         m_veto=StringFormat("invalidation %.1f units away - too deep for this volatility",risk/unit);
         m_context=StringFormat("%s %s - %s, but %s",SmcDirShort(dir),m_playbook,why,m_veto);
         BuildContextFactors(dir);
         return(false);
        }

      double tp1=0.0,tp2=0.0;
      string t1name="",t2name="";
      double t1w=0.0;
      if(!m_e.NextTarget(dir,entry,risk*1.2,tp1,t1name,t1w))
        {
         if(!m_e.RangeTarget(dir,entry,tp1))
           {
            m_veto="no unswept liquidity to target";
            m_context=StringFormat("%s %s - %s, but %s",SmcDirShort(dir),m_playbook,why,m_veto);
            BuildContextFactors(dir);
            return(false);
           }
         t1name="range extreme";
        }
      if(!m_e.RangeTarget(dir,entry,tp2) || (dir==DIR_BULL?tp2<=tp1:tp2>=tp1))
         tp2=(dir==DIR_BULL?entry+(tp1-entry)*1.8:entry-(entry-tp1)*1.8);

      double rr1=SmcSafeDiv(MathAbs(tp1-entry),risk,0.0);
      double rr2=SmcSafeDiv(MathAbs(tp2-entry),risk,0.0);

      //--- factor measurement ----------------------------------------
      BuildFactors(dir,zone,entry,sl,tp1,rr1,post_news,ne,why);

      //--- probability -------------------------------------------------
      double prob=(m_model!=NULL?m_model.BlendedProbability(m_x):SmcSigmoid(0.0));
      double score=(m_model!=NULL?m_model.Score(m_x):0.0);

      //--- expectancy gate: the objective must pay for the probability --
      double rr_needed=MathMax(1.30,SmcSafeDiv(1.0-prob,prob,2.0)*1.80);
      if(rr1<rr_needed)
        {
         m_veto=StringFormat("reward %.2fR below the %.2fR that a %.0f%% setup must earn",rr1,rr_needed,prob*100.0);
         m_context=StringFormat("%s %s - %s. Rejected: %s",SmcDirShort(dir),m_playbook,why,m_veto);
         sig.valid=false;
         sig.dir=dir;
         sig.prob=prob;
         sig.raw_score=score;
         sig.rr1=rr1;
         return(false);
        }

      //--- news veto ---------------------------------------------------
      if(m_news!=NULL)
        {
         string evn="";
         int mins=0;
         if(m_news.InBlackout(SmcNow(),m_news_block_before,m_news_block_after,m_news_importance,evn,mins))
           {
            m_veto=StringFormat("inside the release window of %s (%+d min)",evn,mins);
            m_context=StringFormat("%s %s - %s. Rejected: %s",SmcDirShort(dir),m_playbook,why,m_veto);
            sig.valid=false;
            sig.dir=dir;
            sig.prob=prob;
            sig.raw_score=score;
            sig.rr1=rr1;
            return(false);
           }
        }

      //--- spread veto -------------------------------------------------
      double spread=m_ms.SpreadPrice();
      if(spread>risk*0.20)
        {
         m_veto=StringFormat("spread %.2f is %.0f%% of the planned risk",spread,spread/risk*100.0);
         m_context=StringFormat("%s %s - %s. Rejected: %s",SmcDirShort(dir),m_playbook,why,m_veto);
         sig.valid=false;
         sig.dir=dir;
         sig.prob=prob;
         sig.raw_score=score;
         return(false);
        }

      sig.valid=true;
      sig.dir=dir;
      sig.entry=entry;
      sig.sl=sl;
      sig.tp1=tp1;
      sig.tp2=tp2;
      sig.prob=prob;
      sig.raw_score=score;
      sig.rr1=rr1;
      sig.rr2=rr2;
      sig.model=m_playbook;
      sig.bar_time=bt;
      sig.zone_top=zone.top;
      sig.zone_bottom=zone.bottom;
      sig.idm=zone.idm;
      sig.idm_taken=zone.idm_taken;
      sig.rationale=BuildRationale(dir,zone,why,t1name,rr1,prob);
      m_context=sig.rationale;
      return(true);
     }

   //--- factor block used when there is no directional hypothesis -----
   void              BuildContextFactors(const int dir)
     {
      int d=(dir==DIR_NONE?DIR_BULL:dir);
      string lbl="";
      SetFactor(F_HTF_BIAS,"HTF structure",m_bias_htf,
                (m_bias_htf==DIR_NONE?0.0:Orient(m_bias_htf==DIR_BULL?0.8:-0.8,d)),
                StringFormat("%s on %s",SmcDirStr(m_bias_htf),EnumToString(m_ms.TfHigh())));
      SetFactor(F_MID_BIAS,"Mid structure",m_bias_mid,
                (m_bias_mid==DIR_NONE?0.0:Orient(m_bias_mid==DIR_BULL?0.8:-0.8,d)),
                StringFormat("%s on %s",SmcDirStr(m_bias_mid),EnumToString(m_ms.TfMid())));
      SetFactor(F_STRUCTURE,"Entry structure",m_e.Trend(),0.0,
                StringFormat("swing %s / internal %s",SmcDirStr(m_e.Trend()),SmcDirStr(m_e.InternalTrend())));
      SetFactor(F_SWEEP,"Liquidity raid",m_e.SweepQuality(),0.0,
                (m_e.SweepValid()?StringFormat("%s raid %d bars ago",m_e.SweepPool(),m_e.SweepAge()):"no fresh raid"));
      SetFactor(F_OB_QUALITY,"Order block",0.0,0.0,"none engaged");
      SetFactor(F_FVG_CONF,"Imbalance",0.0,0.0,"none engaged");
      double pos=m_e.RangePosition(SymbolInfoDouble(m_ms.Symbol(),SYMBOL_BID));
      SetFactor(F_PREM_DISC,"Premium/discount",pos,0.0,
                StringFormat("%.0f%% of range (%s)",pos*100.0,(pos>0.5?"premium":"discount")));
      SetFactor(F_DISPLACEMENT,"Displacement",0.0,0.0,"waiting");
      double ss=SessionScore(SmcNow(),lbl);
      SetFactor(F_SESSION,"Session",ss,ss,lbl);
      double vr=m_ms.VolRegime();
      SetFactor(F_VOLATILITY,"Volatility regime",vr,VolScore(vr),VolNote(vr));
      double sp=m_ms.SpreadUnits();
      SetFactor(F_EXECUTION,"Execution cost",sp,SmcClamp(1.0-sp/0.30,-1.0,1.0),
                StringFormat("spread %.2f of a median candle",sp));
      SetFactor(F_RR,"Reward:risk",0.0,0.0,"no objective mapped");
      SetFactor(F_KEYLEVEL,"Key levels",0.0,0.0,(m_has_day?"PDH/PDL loaded":"daily levels unavailable"));
      SetFactor(F_CANDLE,"Confirmation",0.0,0.0,"no confirmation candle");
      SetFactor(F_VOLUME,"Participation",0.0,0.0,"neutral");
      double nsc=NewsScore(false);
      SetFactor(F_NEWS,"News context",nsc,nsc,(m_news!=NULL?m_news.Describe(SmcNow(),m_news_importance):"news feed off"));
      SetFactor(F_INDUCEMENT,"Inducement",0.0,0.0,"no zone engaged");
     }

   double            VolScore(const double vr)
     {
      if(vr<0.55) return(-0.85);
      if(vr<0.80) return(-0.35);
      if(vr<=1.80) return(SmcClamp((vr-0.80)/0.6,0.0,1.0));
      if(vr<=2.60) return(0.35);
      return(-0.45);
     }
   string            VolNote(const double vr)
     {
      if(vr<0.55) return(StringFormat("compressed tape (%.2fx normal) - raids fail to follow through",vr));
      if(vr>2.60) return(StringFormat("violent expansion (%.2fx normal) - slippage risk",vr));
      return(StringFormat("%.2fx the normal candle - workable",vr));
     }

   double            NewsScore(const bool post_news)
     {
      if(m_news==NULL) return(0.0);
      SNewsEvent e;
      int mins=0;
      double s=0.0;
      if(m_news.NextEvent(SmcNow(),m_news_importance,e,mins))
        {
         if(mins<=m_news_block_before)      s=-1.00;
         else if(mins<=45)                  s=-0.55;
         else if(mins<=120)                 s=-0.15;
         else                               s= 0.10;
        }
      else s=0.10;
      if(post_news) s=MathMax(s,0.75);      // the raid the release engineered
      return(s);
     }

   //+---------------------------------------------------------------+
   //| Measure every confluence factor for the proposed direction     |
   //+---------------------------------------------------------------+
   void              BuildFactors(const int dir,const SZone &zone,const double entry,const double sl,
                                  const double tp1,const double rr1,const bool post_news,
                                  const SNewsEvent &ne,const string why)
     {
      double unit=m_e.Unit();
      double conv_h=0.0,conv_m=0.0;
      int bh=EngineBias(m_h,conv_h);
      int bm=EngineBias(m_m,conv_m);

      //--- 0 higher timeframe narrative
      double s_htf=(bh==DIR_NONE?0.0:Orient(bh==DIR_BULL?1.0:-1.0,dir)*conv_h);
      SetFactor(F_HTF_BIAS,"HTF structure",bh,s_htf,
                StringFormat("%s is %s (conviction %.0f%%)",EnumToString(m_ms.TfHigh()),SmcDirStr(bh),conv_h*100.0));

      //--- 1 intermediate timeframe
      double s_mid=(bm==DIR_NONE?0.0:Orient(bm==DIR_BULL?1.0:-1.0,dir)*conv_m);
      SetFactor(F_MID_BIAS,"Mid structure",bm,s_mid,
                StringFormat("%s is %s (conviction %.0f%%)",EnumToString(m_ms.TfMid()),SmcDirStr(bm),conv_m*100.0));

      //--- 2 entry timeframe structure shift
      double s_str=0.0;
      string n_str="";
      bool choch=(m_e.LastChochDir()==dir && m_e.LastChochTime()>=m_e.SweepTime() && m_e.SweepTime()>0);
      bool bos  =(m_e.LastBosDir()==dir);
      if(choch)      { s_str= 1.00; n_str="CHoCH in trade direction after the raid"; }
      else if(bos)   { s_str= 0.70; n_str="BOS in trade direction"; }
      else if(m_e.InternalTrend()==dir) { s_str=0.40; n_str="internal structure turned"; }
      else           { s_str=-0.50; n_str="structure has not confirmed yet"; }
      if(m_e.Trend()==dir) s_str=MathMin(1.0,s_str+0.20);
      SetFactor(F_STRUCTURE,"Entry structure",m_e.Trend(),s_str,n_str);

      //--- 3 liquidity raid quality
      double s_swp=-0.35;
      string n_swp="no raid preceding this setup";
      if(m_e.SweepValid() && m_e.SweepDir()==dir)
        {
         int age=m_e.SweepAge();
         double fresh=SmcClamp(1.0-(double)(age-1)/(double)MathMax(m_e.PivotLen()*4,4),0.10,1.0);
         s_swp=SmcClamp(0.35+m_e.SweepQuality()*1.2,0.0,1.0)*fresh;
         n_swp=StringFormat("%s swept %d bars ago, rejection quality %.2f",m_e.SweepPool(),age,m_e.SweepQuality());
        }
      SetFactor(F_SWEEP,"Liquidity raid",m_e.SweepQuality(),s_swp,n_swp);

      //--- 4 order block quality
      double s_ob=zone.strength*2.0-0.6;
      string n_ob=StringFormat("%s %s, displacement %.1f candles, %s",
                               SmcDirStr(zone.dir),SmcZoneStr(zone.kind),zone.displacement,
                               (zone.mitigated?"already tapped":"untouched"));
      if(zone.mitigated) s_ob-=0.25;
      SetFactor(F_OB_QUALITY,"Order block",zone.strength,SmcClamp(s_ob,-1.0,1.0),n_ob);

      //--- 5 imbalance confluence
      bool overlap_fvg=m_e.HasOverlap(dir,zone.top,zone.bottom,ZONE_FVG);
      bool overlap_ob =m_e.HasOverlap(dir,zone.top,zone.bottom,ZONE_OB);
      double s_fvg=0.0;
      string n_fvg="zone stands alone";
      if(overlap_fvg && zone.kind==ZONE_OB) { s_fvg=1.00; n_fvg="order block sitting inside an unfilled imbalance"; }
      else if(overlap_ob && zone.kind==ZONE_FVG) { s_fvg=0.90; n_fvg="imbalance backed by an order block"; }
      else if(zone.has_fvg) { s_fvg=0.55; n_fvg="zone created with displacement imbalance"; }
      else s_fvg=-0.30;
      SetFactor(F_FVG_CONF,"Imbalance",(overlap_fvg?1.0:0.0),s_fvg,n_fvg);

      //--- 6 premium / discount location
      double pos=m_e.RangePosition(entry);
      double s_pd;
      if(dir==DIR_BULL) s_pd=SmcClamp((0.5-pos)*3.0,-1.0,1.0);
      else              s_pd=SmcClamp((pos-0.5)*3.0,-1.0,1.0);
      string n_pd=StringFormat("entry at %.0f%% of the dealing range (%s) - %s",
                               pos*100.0,(pos>0.5?"premium":"discount"),
                               (s_pd>0?"correct side":"wrong side of equilibrium"));
      SetFactor(F_PREM_DISC,"Premium/discount",pos,s_pd,n_pd);

      //--- 7 displacement energy of the confirming leg
      double leg=0.0;
      int look=(int)MathMax(3,m_e.PivotLen()*2);
      for(int b=1;b<=look;b++)
        {
         double body=MathAbs(m_ms.EClose(b)-m_ms.EOpen(b));
         if((dir==DIR_BULL && m_ms.EClose(b)>m_ms.EOpen(b)) || (dir==DIR_BEAR && m_ms.EClose(b)<m_ms.EOpen(b)))
            leg=MathMax(leg,body);
        }
      double s_disp=SmcClamp(SmcSafeDiv(leg,m_ms.BodyP80(),0.0)-0.6,-1.0,1.0);
      SetFactor(F_DISPLACEMENT,"Displacement",SmcSafeDiv(leg,unit,0.0),s_disp,
                StringFormat("strongest %s body in the last %d bars = %.1f median candles",
                             (dir==DIR_BULL?"up":"down"),look,SmcSafeDiv(leg,unit,0.0)));

      //--- 8 session
      string lbl="";
      double s_ses=SessionScore(SmcNow(),lbl);
      SetFactor(F_SESSION,"Session",s_ses,s_ses,lbl);

      //--- 9 volatility regime
      double vr=m_ms.VolRegime();
      SetFactor(F_VOLATILITY,"Volatility regime",vr,VolScore(vr),VolNote(vr));

      //--- 10 execution cost
      double sp=m_ms.SpreadPrice();
      double risk=MathAbs(entry-sl);
      double sp_ratio=SmcSafeDiv(sp,risk,1.0);
      double s_exec=SmcClamp(1.0-sp_ratio/0.12,-1.0,1.0);
      SetFactor(F_EXECUTION,"Execution cost",sp_ratio,s_exec,
                StringFormat("spread is %.1f%% of the stop distance",sp_ratio*100.0));

      //--- 11 reward to risk
      double s_rr=SmcClamp((rr1-1.5)/1.5,-1.0,1.0);
      SetFactor(F_RR,"Reward:risk",rr1,s_rr,StringFormat("%.2fR to the first liquidity objective",rr1));

      //--- 12 key level confluence
      string kl="";
      double d_key=NearestKeyLevelDistance((zone.top+zone.bottom)*0.5,kl);
      double s_key=0.0;
      string n_key="no daily/weekly level near the zone";
      if(d_key>=0.0)
        {
         double u=SmcSafeDiv(d_key,unit,9.9);
         s_key=SmcClamp(1.0-u/1.5,-0.5,1.0);
         n_key=StringFormat("%s is %.1f candles from the zone",kl,u);
        }
      SetFactor(F_KEYLEVEL,"Key levels",d_key,s_key,n_key);

      //--- 13 confirmation candle
      double h=m_ms.EHigh(1),l=m_ms.ELow(1),c=m_ms.EClose(1),o=m_ms.EOpen(1);
      double rng=MathMax(h-l,1e-10);
      double close_pos=(c-l)/rng;
      double s_cnd=(dir==DIR_BULL?(close_pos-0.5)*2.0:(0.5-close_pos)*2.0);
      double wick=(dir==DIR_BULL?(MathMin(c,o)-l)/rng:(h-MathMax(c,o))/rng);
      s_cnd=SmcClamp(s_cnd*0.7+wick*0.6,-1.0,1.0);
      SetFactor(F_CANDLE,"Confirmation",close_pos,s_cnd,
                StringFormat("close in the %.0f%% of the bar range with a %.0f%% rejection wick",
                             close_pos*100.0,wick*100.0));

      //--- 14 participation
      double vratio=SmcSafeDiv((double)m_ms.EVol(1),m_ms.TickVolMed(),1.0);
      double s_vol=SmcClamp((vratio-1.0)/1.2,-1.0,1.0);
      SetFactor(F_VOLUME,"Participation",vratio,s_vol,
                StringFormat("confirmation bar traded %.2fx the median tick volume",vratio));

      //--- 16 inducement: has the trap in front of this zone been sprung
      double s_idm=0.0;
      string n_idm="";
      if(zone.idm<=0.0)
        {
         s_idm=0.15;
         n_idm="no interior pullback in the creating leg - nothing resting in front of the zone";
        }
      else if(zone.idm_taken)
        {
         s_idm=1.00;
         n_idm=StringFormat("inducement at %.2f has been run - the zone is armed",zone.idm);
        }
      else
        {
         //--- a continuation entry that has not taken its inducement is
         //--- the classic premature tap; after a major raid it is milder
         bool continuation=(StringFind(m_playbook,"C -")==0);
         s_idm=(continuation?-0.90:-0.45);
         n_idm=StringFormat("inducement at %.2f still resting - the trap has not been sprung",zone.idm);
        }
      SetFactor(F_INDUCEMENT,"Inducement",zone.idm,s_idm,n_idm);

      //--- 15 news context
      double s_news=NewsScore(post_news);
      string n_news=(m_news!=NULL?m_news.Describe(SmcNow(),m_news_importance):"news feed off");
      if(post_news) n_news=StringFormat("raid after %s (%s) - engineered liquidity",ne.name,ne.currency);
      SetFactor(F_NEWS,"News context",s_news,s_news,n_news);
     }

   //--- natural language summary of the decision ----------------------
   string            BuildRationale(const int dir,const SZone &zone,const string why,
                                    const string target_name,const double rr1,const double prob)
     {
      //--- rank the three strongest supporting measurements
      int idx[3]={-1,-1,-1};
      double val[3]={-9,-9,-9};
      for(int i=0;i<F_COUNT;i++)
        {
         double c=m_f[i].contrib;
         if(c>val[0]) { val[2]=val[1]; idx[2]=idx[1]; val[1]=val[0]; idx[1]=idx[0]; val[0]=c; idx[0]=i; }
         else if(c>val[1]) { val[2]=val[1]; idx[2]=idx[1]; val[1]=c; idx[1]=i; }
         else if(c>val[2]) { val[2]=c; idx[2]=i; }
        }
      string top="";
      for(int k=0;k<3;k++)
         if(idx[k]>=0 && val[k]>0.0)
            top+=StringFormat("%s(%s%.2f) ",m_f[idx[k]].name,(val[k]>=0?"+":""),val[k]);

      string worst="";
      double wv=9.0;
      int wi=-1;
      for(int i=0;i<F_COUNT;i++)
         if(m_f[i].contrib<wv) { wv=m_f[i].contrib; wi=i; }
      if(wi>=0 && wv<0.0) worst=StringFormat(" Main objection: %s (%.2f) - %s.",m_f[wi].name,wv,m_f[wi].note);

      return(StringFormat("%s %s. %s. Trading from the %s %s at %.2f-%.2f towards %s for %.2fR. Model confidence %.0f%%. Top evidence: %s.%s",
                          SmcDirShort(dir),m_playbook,why,SmcDirStr(zone.dir),SmcZoneStr(zone.kind),
                          zone.bottom,zone.top,target_name,rr1,prob*100.0,top,worst));
     }
  };

#endif // __SMC_CONFLUENCE_MQH__
