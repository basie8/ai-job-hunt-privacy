//+------------------------------------------------------------------+
//|                                                      Visuals.mqh |
//|                                                                  |
//|  Everything the agent sees is drawn on the chart, in the same     |
//|  language a LuxAlgo "Smart Money Concepts" user reads:            |
//|    order blocks, imbalances, BOS / CHoCH, equal highs and lows,   |
//|    daily / weekly / session liquidity, the dealing range with     |
//|    premium - equilibrium - discount, the raid that triggered the  |
//|    setup, the killzones, and a live decision panel with every     |
//|    confluence factor, its learned weight and its contribution.    |
//+------------------------------------------------------------------+
#ifndef __SMC_VISUALS_MQH__
#define __SMC_VISUALS_MQH__

#include "Defs.mqh"
#include "MarketState.mqh"
#include "SmcEngine.mqh"
#include "Confluence.mqh"
#include "RiskManager.mqh"
#include "Learner.mqh"

#define VIS_PREFIX "SMCAI_"

class CVisuals
  {
private:
   long              m_chart;
   int               m_sub;
   bool              m_draw_chart;
   bool              m_draw_panel;
   int               m_x;
   int               m_y;
   int               m_row_h;
   int               m_width;
   int               m_font;
   string            m_font_name;

   color             m_c_bull;
   color             m_c_bear;
   color             m_c_bull_soft;
   color             m_c_bear_soft;
   color             m_c_fvg_bull;
   color             m_c_fvg_bear;
   color             m_c_text;
   color             m_c_dim;
   color             m_c_panel;
   color             m_c_accent;

   int               m_row;

   //--- object helpers ----------------------------------------------
   bool              Exists(const string n) { return(ObjectFind(m_chart,n)>=0); }

   void              Label(const string id,const int x,const int y,const string text,const color clr,
                           const int size=8,const string font="")
     {
      string n=VIS_PREFIX+id;
      if(!Exists(n))
        {
         ObjectCreate(m_chart,n,OBJ_LABEL,m_sub,0,0);
         ObjectSetInteger(m_chart,n,OBJPROP_CORNER,CORNER_LEFT_UPPER);
         ObjectSetInteger(m_chart,n,OBJPROP_SELECTABLE,false);
         ObjectSetInteger(m_chart,n,OBJPROP_HIDDEN,true);
         ObjectSetInteger(m_chart,n,OBJPROP_BACK,false);
        }
      ObjectSetInteger(m_chart,n,OBJPROP_XDISTANCE,x);
      ObjectSetInteger(m_chart,n,OBJPROP_YDISTANCE,y);
      ObjectSetInteger(m_chart,n,OBJPROP_COLOR,clr);
      ObjectSetInteger(m_chart,n,OBJPROP_FONTSIZE,size);
      ObjectSetString(m_chart,n,OBJPROP_FONT,(font==""?m_font_name:font));
      ObjectSetString(m_chart,n,OBJPROP_TEXT,text);
     }

   void              Panel(const string id,const int x,const int y,const int w,const int h,const color bg,const color border)
     {
      string n=VIS_PREFIX+id;
      if(!Exists(n))
        {
         ObjectCreate(m_chart,n,OBJ_RECTANGLE_LABEL,m_sub,0,0);
         ObjectSetInteger(m_chart,n,OBJPROP_CORNER,CORNER_LEFT_UPPER);
         ObjectSetInteger(m_chart,n,OBJPROP_SELECTABLE,false);
         ObjectSetInteger(m_chart,n,OBJPROP_HIDDEN,true);
         ObjectSetInteger(m_chart,n,OBJPROP_BACK,false);
         ObjectSetInteger(m_chart,n,OBJPROP_BORDER_TYPE,BORDER_FLAT);
        }
      ObjectSetInteger(m_chart,n,OBJPROP_XDISTANCE,x);
      ObjectSetInteger(m_chart,n,OBJPROP_YDISTANCE,y);
      ObjectSetInteger(m_chart,n,OBJPROP_XSIZE,w);
      ObjectSetInteger(m_chart,n,OBJPROP_YSIZE,h);
      ObjectSetInteger(m_chart,n,OBJPROP_BGCOLOR,bg);
      ObjectSetInteger(m_chart,n,OBJPROP_COLOR,border);
     }

   void              Box(const string id,const datetime t1,const double p1,const datetime t2,const double p2,
                         const color clr,const bool fill,const int style=STYLE_SOLID,const int width=1)
     {
      string n=VIS_PREFIX+id;
      if(!Exists(n))
        {
         ObjectCreate(m_chart,n,OBJ_RECTANGLE,m_sub,t1,p1,t2,p2);
         ObjectSetInteger(m_chart,n,OBJPROP_SELECTABLE,false);
         ObjectSetInteger(m_chart,n,OBJPROP_HIDDEN,true);
         ObjectSetInteger(m_chart,n,OBJPROP_BACK,true);
        }
      ObjectMove(m_chart,n,0,t1,p1);
      ObjectMove(m_chart,n,1,t2,p2);
      ObjectSetInteger(m_chart,n,OBJPROP_COLOR,clr);
      ObjectSetInteger(m_chart,n,OBJPROP_FILL,fill);
      ObjectSetInteger(m_chart,n,OBJPROP_STYLE,style);
      ObjectSetInteger(m_chart,n,OBJPROP_WIDTH,width);
     }

   void              Line(const string id,const datetime t1,const double p1,const datetime t2,const double p2,
                          const color clr,const int style=STYLE_SOLID,const int width=1,const bool ray=false)
     {
      string n=VIS_PREFIX+id;
      if(!Exists(n))
        {
         ObjectCreate(m_chart,n,OBJ_TREND,m_sub,t1,p1,t2,p2);
         ObjectSetInteger(m_chart,n,OBJPROP_SELECTABLE,false);
         ObjectSetInteger(m_chart,n,OBJPROP_HIDDEN,true);
         ObjectSetInteger(m_chart,n,OBJPROP_BACK,true);
        }
      ObjectMove(m_chart,n,0,t1,p1);
      ObjectMove(m_chart,n,1,t2,p2);
      ObjectSetInteger(m_chart,n,OBJPROP_COLOR,clr);
      ObjectSetInteger(m_chart,n,OBJPROP_STYLE,style);
      ObjectSetInteger(m_chart,n,OBJPROP_WIDTH,width);
      ObjectSetInteger(m_chart,n,OBJPROP_RAY_RIGHT,ray);
     }

   void              Text(const string id,const datetime t,const double p,const string txt,const color clr,const int size=7)
     {
      string n=VIS_PREFIX+id;
      if(!Exists(n))
        {
         ObjectCreate(m_chart,n,OBJ_TEXT,m_sub,t,p);
         ObjectSetInteger(m_chart,n,OBJPROP_SELECTABLE,false);
         ObjectSetInteger(m_chart,n,OBJPROP_HIDDEN,true);
         ObjectSetInteger(m_chart,n,OBJPROP_BACK,false);
         ObjectSetInteger(m_chart,n,OBJPROP_ANCHOR,ANCHOR_LEFT);
        }
      ObjectMove(m_chart,n,0,t,p);
      ObjectSetInteger(m_chart,n,OBJPROP_COLOR,clr);
      ObjectSetInteger(m_chart,n,OBJPROP_FONTSIZE,size);
      ObjectSetString(m_chart,n,OBJPROP_FONT,m_font_name);
      ObjectSetString(m_chart,n,OBJPROP_TEXT,txt);
     }

   void              Arrow(const string id,const datetime t,const double p,const int code,const color clr,const int size=1)
     {
      string n=VIS_PREFIX+id;
      if(!Exists(n))
        {
         ObjectCreate(m_chart,n,OBJ_ARROW,m_sub,t,p);
         ObjectSetInteger(m_chart,n,OBJPROP_SELECTABLE,false);
         ObjectSetInteger(m_chart,n,OBJPROP_HIDDEN,true);
        }
      ObjectMove(m_chart,n,0,t,p);
      ObjectSetInteger(m_chart,n,OBJPROP_ARROWCODE,code);
      ObjectSetInteger(m_chart,n,OBJPROP_COLOR,clr);
      ObjectSetInteger(m_chart,n,OBJPROP_WIDTH,size);
     }

   string            Bar(const double score,const int cells=8)
     {
      int filled=(int)MathRound(MathAbs(score)*cells);
      string s="";
      for(int i=0;i<cells;i++) s+=(i<filled?"|":".");
      return(s);
     }

   void              DeleteGroup(const string sub)
     { ObjectsDeleteAll(m_chart,VIS_PREFIX+sub,m_sub,-1); }

public:
                     CVisuals(void): m_chart(0), m_sub(0), m_draw_chart(true), m_draw_panel(true),
                                     m_x(8), m_y(20), m_row_h(13), m_width(430), m_font(8),
                                     m_font_name("Consolas"), m_row(0)
     {
      m_c_bull=C'46,204,113';
      m_c_bear=C'231,76,60';
      m_c_bull_soft=C'21,84,52';
      m_c_bear_soft=C'96,32,28';
      m_c_fvg_bull=C'26,82,118';
      m_c_fvg_bear=C'110,68,20';
      m_c_text=C'220,221,225';
      m_c_dim=C'128,133,145';
      m_c_panel=C'18,20,26';
      m_c_accent=C'241,196,15';
     }

   void              Init(const long chart_id,const bool draw_chart,const bool draw_panel,
                          const int panel_x,const int panel_y)
     {
      m_chart=chart_id;
      m_draw_chart=draw_chart;
      m_draw_panel=draw_panel;
      m_x=panel_x;
      m_y=panel_y;
     }

   void              Clear(void) { ObjectsDeleteAll(m_chart,VIS_PREFIX,m_sub,-1); ChartRedraw(m_chart); }

   //+---------------------------------------------------------------+
   //| Chart layer                                                    |
   //+---------------------------------------------------------------+
   void              DrawChart(CMarketState *ms,CSmcEngine *eng,CConfluence *conf,const int gmt)
     {
      if(!m_draw_chart || ms==NULL || eng==NULL) return;
      DeleteGroup("Z");
      DeleteGroup("E");
      DeleteGroup("L");
      DeleteGroup("S");
      DeleteGroup("R");
      DeleteGroup("K");

      datetime right=ms.ETime(0)+(datetime)(PeriodSeconds(ms.TfEntry())*12);

      //--- zones: order blocks and imbalances --------------------------
      int zn=eng.ZoneCount();
      int drawn=0;
      for(int i=zn-1;i>=0 && drawn<26;i--)
        {
         SZone z;
         if(!eng.GetZone(i,z)) continue;
         if(z.broken) continue;
         color c;
         if(z.kind==ZONE_FVG) c=(z.dir==DIR_BULL?m_c_fvg_bull:m_c_fvg_bear);
         else                 c=(z.dir==DIR_BULL?m_c_bull_soft:m_c_bear_soft);
         string id=StringFormat("Z_%d",(int)z.uid);
         Box(id,z.t_from,z.top,right,z.bottom,c,true,STYLE_SOLID,1);
         Text(id+"_t",z.t_from,z.top,StringFormat(" %s %s%s",SmcZoneStr(z.kind),
              (z.dir==DIR_BULL?"+":"-"),(z.mitigated?" (tapped)":"")),
              (z.dir==DIR_BULL?m_c_bull:m_c_bear),7);
         drawn++;
        }

      //--- structure events -------------------------------------------
      int en=eng.EventCount();
      int ec=0;
      for(int i=en-1;i>=0 && ec<14;i--)
        {
         SStructEvent e;
         if(!eng.GetEvent(i,e)) continue;
         color c=(e.dir==DIR_BULL?m_c_bull:m_c_bear);
         int style=(e.internal?STYLE_DOT:STYLE_DASH);
         string id=StringFormat("E_%d",i);
         Line(id,e.origin,e.level,e.time,e.level,c,style,(e.internal?1:2),false);
         Text(id+"_t",e.time,e.level,StringFormat(" %s%s",(e.kind==EV_CHOCH?"CHoCH":"BOS"),(e.internal?"(i)":"")),c,7);
         ec++;
        }

      //--- liquidity pools --------------------------------------------
      int ln=eng.LiqCount();
      for(int i=0;i<ln;i++)
        {
         SLiquidity q;
         if(!eng.GetLiq(i,q)) continue;
         color c=(q.swept?m_c_dim:(q.dir==DIR_BULL?m_c_bear:m_c_bull));
         int style=(q.swept?STYLE_DOT:STYLE_DASHDOT);
         string id=StringFormat("L_%d",i);
         Line(id,q.time,q.price,right,q.price,c,style,1,false);
         Text(id+"_t",right,q.price,StringFormat(" %s%s",SmcLiqStr(q.kind),(q.swept?" swept":"")),c,7);
        }

      //--- dealing range: premium / equilibrium / discount --------------
      double hi,lo;
      if(eng.Range(hi,lo))
        {
         datetime t0=(datetime)MathMin((long)eng.RangeHiTime(),(long)eng.RangeLoTime());
         double eq=(hi+lo)*0.5;
         Box("R_prem",t0,hi,right,eq,C'60,30,40',false,STYLE_DOT,1);
         Box("R_disc",t0,eq,right,lo,C'30,60,45',false,STYLE_DOT,1);
         Line("R_eq",t0,eq,right,eq,m_c_accent,STYLE_DASH,1,false);
         Text("R_eq_t",right,eq," EQUILIBRIUM",m_c_accent,7);
         Text("R_p_t",right,hi," PREMIUM",m_c_bear,7);
         Text("R_d_t",right,lo," DISCOUNT",m_c_bull,7);
        }

      //--- the raid that armed the current hypothesis -------------------
      if(eng.SweepValid())
        {
         color c=(eng.SweepDir()==DIR_BULL?m_c_bull:m_c_bear);
         Arrow("S_sweep",eng.SweepTime(),eng.SweepExtreme(),(eng.SweepDir()==DIR_BULL?233:234),c,2);
         Text("S_sweep_t",eng.SweepTime(),eng.SweepExtreme(),
              StringFormat(" RAID %s (q=%.2f)",eng.SweepPool(),eng.SweepQuality()),c,7);
        }

      //--- session killzones of the current day -------------------------
      datetime day0=SmcDayStart(TimeCurrent());
      for(int d=0;d<2;d++)
        {
         datetime base=day0-(datetime)(d*86400);
         DrawKz(StringFormat("K_L%d",d),base,7,10,gmt,C'30,42,60');
         DrawKz(StringFormat("K_N%d",d),base,12,15,gmt,C'46,36,60');
        }
      ChartRedraw(m_chart);
     }

   void              DrawKz(const string id,const datetime day0,const double gmt_from,const double gmt_to,
                            const int gmt,const color clr)
     {
      //--- convert a GMT window into server time for this day
      datetime t1=day0+(datetime)((int)((gmt_from+gmt)*3600));
      datetime t2=day0+(datetime)((int)((gmt_to  +gmt)*3600));
      double hi=ChartGetDouble(m_chart,CHART_PRICE_MAX);
      double lo=ChartGetDouble(m_chart,CHART_PRICE_MIN);
      if(hi<=lo) return;
      Box(id,t1,hi,t2,lo,clr,true,STYLE_SOLID,1);
     }

   void              DrawSignal(const SSignal &sig,const datetime from)
     {
      DeleteGroup("G");
      if(!m_draw_chart || !sig.valid) return;
      datetime to=from+(datetime)(PeriodSeconds(PERIOD_CURRENT)*30);
      color c=(sig.dir==DIR_BULL?m_c_bull:m_c_bear);
      Line("G_e",from,sig.entry,to,sig.entry,c,STYLE_SOLID,2,false);
      Line("G_s",from,sig.sl,to,sig.sl,m_c_bear,STYLE_DASH,1,false);
      Line("G_t1",from,sig.tp1,to,sig.tp1,m_c_bull,STYLE_DASH,1,false);
      Line("G_t2",from,sig.tp2,to,sig.tp2,m_c_bull,STYLE_DOT,1,false);
      Text("G_e_t",to,sig.entry,StringFormat(" %s @ %.2f (p=%.0f%%)",SmcDirShort(sig.dir),sig.entry,sig.prob*100.0),c,8);
      Text("G_s_t",to,sig.sl," SL",m_c_bear,7);
      Text("G_t1_t",to,sig.tp1,StringFormat(" TP1 %.2fR",sig.rr1),m_c_bull,7);
      Text("G_t2_t",to,sig.tp2,StringFormat(" TP2 %.2fR",sig.rr2),m_c_bull,7);
     }

   //+---------------------------------------------------------------+
   //| Decision panel                                                 |
   //+---------------------------------------------------------------+
   void              Row(const string id,const string text,const color clr,const int size=8)
     {
      //--- every panel object lives under the P_ group so that the
      //--- chart layer can be cleared without touching the panel
      Label("P_"+id,m_x+8,m_y+6+m_row*m_row_h,text,clr,size);
      m_row++;
     }

   void              DrawPanel(CMarketState *ms,CSmcEngine *eng,CConfluence *conf,CRiskManager *risk,
                               COnlineLearner *model,const SSignal &sig,const string mode,
                               const double threshold,const string last_action,const int open_positions,
                               const string news_line)
     {
      if(!m_draw_panel) return;
      int rows=14+F_COUNT;
      int h=rows*m_row_h+22;
      Panel("P_BG",m_x,m_y,m_width,h,m_c_panel,C'60,64,74');
      m_row=0;

      Row("h1",StringFormat("%s v%s   %s %s   %s",SMC_AGENT_NAME,SMC_AGENT_VERSION,ms.Symbol(),
          EnumToString(ms.TfEntry()),TimeToString(TimeCurrent(),TIME_DATE|TIME_MINUTES)),m_c_accent,9);

      color mode_c=(mode=="LIVE"?m_c_bull:(mode=="LOCKED"?m_c_bear:m_c_accent));
      Row("h2",StringFormat("MODE %-10s  model %s  samples %d  acc %.0f%%  thr %.0f%%",
          mode,(model.IsWarm()?"trained":StringFormat("warm-up %d/%d",(int)model.Updates(),model.WarmupNeeded())),
          model.Samples(),model.Accuracy()*100.0,threshold*100.0),mode_c,8);

      Row("h3",StringFormat("STRUCTURE  %s %s | %s %s | %s swing %s / internal %s",
          EnumToString(ms.TfHigh()),SmcDirStr(conf.BiasHtf()),
          EnumToString(ms.TfMid()),SmcDirStr(conf.BiasMid()),
          EnumToString(ms.TfEntry()),SmcDirStr(eng.Trend()),SmcDirStr(eng.InternalTrend())),m_c_text,8);

      double hi,lo;
      string rng="range not mapped";
      if(eng.Range(hi,lo))
         rng=StringFormat("range %.2f - %.2f  price at %.0f%% (%s)",lo,hi,
             eng.RangePosition(SymbolInfoDouble(ms.Symbol(),SYMBOL_BID))*100.0,
             (eng.RangePosition(SymbolInfoDouble(ms.Symbol(),SYMBOL_BID))>0.5?"premium":"discount"));
      Row("h4",StringFormat("DEALING    %s | raid %s",rng,
          (eng.SweepValid()?StringFormat("%s %s %d bars ago",eng.SweepPool(),SmcDirStr(eng.SweepDir()),eng.SweepAge()):"none")),
          m_c_dim,8);

      Row("h5",StringFormat("PLAYBOOK   %s",conf.Playbook()),m_c_text,8);

      //--- factor table -------------------------------------------------
      Row("f_hdr","FACTOR              SCORE  WEIGHT  CONTRIB  READING",m_c_dim,8);
      double total=0.0;
      for(int i=0;i<F_COUNT;i++)
        {
         SFactor f;
         if(!conf.GetFactor(i,f)) continue;
         total+=f.contrib;
         color c=(f.score>0.15?m_c_bull:(f.score<-0.15?m_c_bear:m_c_dim));
         string note=f.note;
         if(StringLen(note)>34) note=StringSubstr(note,0,34)+"..";
         Row(StringFormat("f%d",i),
             StringFormat("%-18s %s %+0.2f  %+0.2f  %s",f.name,Bar(f.score,5),f.score,f.weight,note),c,8);
        }

      color sc=(total>0?m_c_bull:m_c_bear);
      Row("f_sum",StringFormat("WEIGHTED SCORE %+0.3f  ->  probability %.1f%%  (bias %+0.2f)",
          total,(sig.prob>0?sig.prob*100.0:0.0),model.Bias()),sc,8);

      //--- risk block ---------------------------------------------------
      double dp=risk.DayPnLPct();
      color dc=(dp>=0?m_c_bull:(dp<-2.0?m_c_bear:m_c_accent));
      Row("r1",StringFormat("FTMO P%d    day %+0.2f%% (floor %.2f)  total %+0.2f%%  target %.0f%%  days %d/%d",
          risk.Phase(),dp,risk.DailyFloor(),risk.TotalPnLPct(),risk.TargetProgress()*100.0,
          risk.TradingDays(),risk.MinDays()),dc,8);
      Row("r2",StringFormat("BUDGET     soft stop in %.2f  hard floor in %.2f  open risk %.2f  week trades %d",
          risk.RemainingDailyBudget(),risk.RemainingHardBudget(),risk.OpenRiskMoney(),risk.WeekTrades()),m_c_dim,8);
      Row("r3",StringFormat("NEWS       %s",news_line),m_c_dim,8);

      //--- decision -----------------------------------------------------
      if(sig.valid)
        {
         color c=(sig.dir==DIR_BULL?m_c_bull:m_c_bear);
         Row("d1",StringFormat("SIGNAL     %s  entry %.2f  sl %.2f  tp1 %.2f (%.2fR)  tp2 %.2f (%.2fR)",
             SmcDirShort(sig.dir),sig.entry,sig.sl,sig.tp1,sig.rr1,sig.tp2,sig.rr2),c,8);
        }
      else
        {
         string v=conf.Veto();
         Row("d1",StringFormat("SIGNAL     none - %s",(v==""?"no qualified setup on this close":v)),m_c_dim,8);
        }

      string ctx=conf.Context();
      Row("d2",StringFormat("READING    %s",StringSubstr(ctx,0,72)),m_c_text,8);
      Row("d3",StringFormat("           %s",StringSubstr(ctx,72,72)),m_c_text,8);
      Row("d4",StringFormat("ACTION     %s   open positions %d",last_action,open_positions),m_c_accent,8);

      ChartRedraw(m_chart);
     }
  };

#endif // __SMC_VISUALS_MQH__
