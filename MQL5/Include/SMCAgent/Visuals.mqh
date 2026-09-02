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
#include "TimeZones.mqh"
#include "MarketState.mqh"
#include "SmcEngine.mqh"
#include "Confluence.mqh"
#include "RiskManager.mqh"
#include "Learner.mqh"

#define VIS_PREFIX     "SMCAI_"
#define PANEL_MAX_ROWS 48

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
   int               m_cols;        // panel width measured in characters
   bool              m_compact;
   int               m_last_rows;   // height of the previous render, in rows
   int               m_cw;          // measured width of one character, px
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

   //--- Measure the font rather than assume it. Estimating pixels per
   //--- character is what made the panel overflow its own background:
   //--- MetaTrader renders a point size, and how wide that lands depends
   //--- on the font and the screen. TextGetSize reports the real thing.
   //--- Also verifies the font is actually monospace - if it is not, the
   //--- columns cannot line up and a fixed grid is the wrong tool.
   void              MeasureFont(void)
     {
      string probe="";
      for(int i=0;i<m_cols;i++) probe+="0";
      uint w=0,h=0;
      //--- NEGATIVE size: tenths of a point AND scaled by the screen DPI,
      //--- which is how MetaTrader renders a label. Measuring with the
      //--- positive (DPI independent) form is what made every row come out
      //--- shorter than it actually draws, so the rows overlapped.
      TextSetFont(m_font_name,-m_font*10);
      if(!TextGetSize(probe,w,h) || w==0 || h==0)
        {
         //--- measurement unavailable: fall back generously, never tightly
         m_row_h=(int)MathRound(m_font*2.2);
         m_cw   =(int)MathMax(4,MathRound(m_font*0.80));
         m_width=m_cols*m_cw+22;
         return;
        }
      //--- always leave headroom: a row that is one pixel short overlaps
      //--- its neighbour, which is far worse than a slightly tall panel
      m_row_h=(int)MathMax((int)h+5,(int)MathRound(m_font*2.0));
      m_cw   =(int)MathMax(4,(int)MathRound((double)w/(double)m_cols)+1);
      m_width=m_cols*m_cw+22;

      //--- Never let the panel run off the chart. If the measured width
      //--- does not fit, drop columns until it does rather than spilling
      //--- text over the candles.
      long chart_w=ChartGetInteger(m_chart,CHART_WIDTH_IN_PIXELS);
      if(chart_w>200)
        {
         int room=(int)(chart_w-m_x-16);
         if(m_width>room && m_cw>0)
           {
            m_cols=(int)MathMax(46,MathMin(m_cols,(int)((room-22)/m_cw)));
            m_width=m_cols*m_cw+22;
            Print(StringFormat("SMC AI Agent: panel narrowed to %d columns to fit a %d px chart.",m_cols,(int)chart_w));
           }
        }

      //--- monospace check: a narrow and a wide glyph must measure equal
      uint wn=0,hn=0,ww=0,hw=0;
      TextGetSize("iiiiiiiiii",wn,hn);
      TextGetSize("WWWWWWWWWW",ww,hw);
      if(wn!=ww)
        {
         TextSetFont("Courier New",m_font);
         uint wn2=0,hn2=0,ww2=0,hw2=0;
         TextGetSize("iiiiiiiiii",wn2,hn2);
         TextGetSize("WWWWWWWWWW",ww2,hw2);
         if(wn2==ww2)
           {
            m_font_name="Courier New";
            TextSetFont(m_font_name,m_font);
            TextGetSize(probe,w,h);
            m_width=(int)w+16;
            m_row_h=(int)h+2;
            Print("SMC AI Agent: Consolas is not monospace on this machine - panel switched to Courier New.");
           }
         else
            Print("SMC AI Agent: no monospace font found; panel columns may not line up. Set a monospace font in Visuals.mqh (m_font_name).");
        }
     }

   //--- exactly w characters: padded with spaces or truncated with ".."
   string            Fit(const string src,const int w)
     {
      if(w<=0) return("");
      int len=StringLen(src);
      if(len==w)  return(src);
      if(len<w)
        {
         string out=src;
         for(int i=len;i<w;i++) out+=" ";
         return(out);
        }
      if(w<=2) return(StringSubstr(src,0,w));
      return(StringSubstr(src,0,w-2)+"..");
     }

   //--- right aligned in exactly w characters
   string            FitR(const string src,const int w)
     {
      int len=StringLen(src);
      if(len>=w) return(Fit(src,w));
      string out="";
      for(int i=len;i<w;i++) out+=" ";
      return(out+src);
     }

   //--- a signed magnitude bar that reads at a glance: [--   ] / [  ++]
   string            Bar(const double score,const int half=4)
     {
      int filled=(int)MathRound(MathMin(MathAbs(score),1.0)*half);
      string left="",right="";
      for(int i=0;i<half;i++)
        {
         bool on=(half-i)<=filled;
         left +=(score<0.0 && on?"-":" ");
         right+=((i+1)<=filled && score>0.0?"+":" ");
        }
      return("["+left+right+"]");
     }

   //--- section rule: "-- TITLE -----------------------"
   string            Rule(const string title,const int w)
     {
      string out="-- "+title+" ";
      int len=StringLen(out);
      for(int i=len;i<w;i++) out+="-";
      return(StringSubstr(out,0,w));
     }

   //--- wrap on word boundaries into at most max_lines of width w
   int               Wrap(const string src,const int w,const int max_lines,string &out[])
     {
      ArrayResize(out,max_lines);
      for(int i=0;i<max_lines;i++) out[i]="";
      string rest=src;
      int used=0;
      while(used<max_lines && StringLen(rest)>0)
        {
         if(StringLen(rest)<=w) { out[used]=rest; used++; break; }
         int cut=-1;
         for(int i=w;i>=(int)(w*0.5);i--)
            if(StringGetCharacter(rest,i)==' ') { cut=i; break; }
         if(cut<0) cut=w;
         out[used]=StringSubstr(rest,0,cut);
         used++;
         rest=StringSubstr(rest,(StringGetCharacter(rest,cut)==' '?cut+1:cut));
        }
      return(used);
     }

   void              DeleteGroup(const string sub)
     { ObjectsDeleteAll(m_chart,VIS_PREFIX+sub,m_sub,-1); }

public:
                     CVisuals(void): m_chart(0), m_sub(0), m_draw_chart(true), m_draw_panel(true),
                                     m_x(8), m_y(20), m_row_h(13), m_width(470), m_font(8),
                                     m_cols(88), m_compact(false), m_last_rows(34), m_cw(8),
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
                          const int panel_x,const int panel_y,const int font_size=10,
                          const bool compact=false,const int width_chars=88)
     {
      m_chart=chart_id;
      //--- An earlier build of the agent used different object names for
      //--- the panel rows. If it did not deinitialise cleanly those labels
      //--- are still on the chart and would show through underneath this
      //--- panel, so start from a blank slate every time.
      ObjectsDeleteAll(m_chart,VIS_PREFIX,m_sub,-1);
      m_draw_chart=draw_chart;
      m_draw_panel=draw_panel;
      m_x=panel_x;
      m_y=panel_y;
      m_font=(int)MathMax(6,MathMin(16,font_size));
      m_compact=compact;
      m_cols=(compact?(int)MathMax(46,width_chars-34):(int)MathMax(46,MathMin(140,width_chars)));
      MeasureFont();
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
      DeleteGroup("I");

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

      //--- inducement guarding each order block -------------------------
      int idmn=0;
      for(int i=zn-1;i>=0 && idmn<8;i--)
        {
         SZone z;
         if(!eng.GetZone(i,z)) continue;
         if(z.broken || z.kind!=ZONE_OB || z.idm<=0.0) continue;
         color c=(z.idm_taken?m_c_dim:m_c_accent);
         string id=StringFormat("I_%d",(int)z.uid);
         Line(id,z.idm_time,z.idm,right,z.idm,c,STYLE_DOT,1,false);
         Text(id+"_t",right,z.idm,(z.idm_taken?" IDM taken":" IDM resting"),c,7);
         idmn++;
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

      //--- session killzones, each in the local time of its own exchange
      datetime now_utc=SmcServerToUtc(SmcNow(),gmt);
      for(int d=0;d<2;d++)
        {
         datetime ldn_day=SmcShift(SmcZoneDayStart(TZ_LONDON,now_utc),-(long)d*86400);
         datetime ny_day =SmcShift(SmcZoneDayStart(TZ_NY,now_utc),    -(long)d*86400);
         DrawKz(StringFormat("K_L%d",d),TZ_LONDON,ldn_day,7.0,10.0,gmt,C'30,42,60');
         DrawKz(StringFormat("K_N%d",d),TZ_NY,    ny_day, 8.0,11.0,gmt,C'46,36,60');
        }
      ChartRedraw(m_chart);
     }

   //--- an exchange-local window on a local day, drawn in server time
   void              DrawKz(const string id,const int zone,const datetime local_day,
                            const double from_h,const double to_h,const int gmt,const color clr)
     {
      datetime t1=0,t2=0;
      SmcZoneWindowToServer(zone,local_day,from_h,to_h,gmt,t1,t2);
      double hi=ChartGetDouble(m_chart,CHART_PRICE_MAX);
      double lo=ChartGetDouble(m_chart,CHART_PRICE_MIN);
      if(hi<=lo || t2<=t1) return;
      Box(id,t1,hi,t2,lo,clr,true,STYLE_SOLID,1);
     }

   //--- remove the entry / stop / target overlay
   void              ClearSignal(void) { DeleteGroup("G"); }

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
      if(sig.idm>0.0)
        {
         Line("G_idm",from,sig.idm,to,sig.idm,m_c_accent,STYLE_DOT,1,false);
         Text("G_idm_t",to,sig.idm,(sig.idm_taken?" IDM taken":" IDM resting"),m_c_accent,7);
        }
     }

   //+---------------------------------------------------------------+
   //| Decision panel                                                 |
   //+---------------------------------------------------------------+
   //+---------------------------------------------------------------+
   //| Decision panel                                                 |
   //|                                                                |
   //| Laid out on a fixed character grid in a monospace font, so the |
   //| columns line up on every terminal and nothing spills past the  |
   //| background. Every row is padded or truncated to exactly m_cols |
   //| characters; the panel is sized from that, not guessed.         |
   //+---------------------------------------------------------------+
   //--- One cell, anchored to an ABSOLUTE pixel offset inside the row.
   //--- Columns therefore line up even if the font turns out not to be
   //--- monospace; only the row height depends on font metrics.
   void              Cell(const int row,const int px,const string text,const color clr,const int chars)
     {
      if(row>=PANEL_MAX_ROWS) return;
      Label(StringFormat("P_r%02d_%04d",row,px),m_x+10+px,m_y+8+row*m_row_h,
            Fit(text,chars),clr,m_font);
     }

   //--- a full width line (titles, section rules)
   void              Row(const string text,const color clr)
     {
      Cell(m_row,0,text,clr,m_cols);
      m_row++;
     }

   //--- label column + value column
   void              KV(const string key,const string val,const color clr)
     {
      Cell(m_row,0,key,m_c_dim,10);
      Cell(m_row,11*m_cw,val,clr,m_cols-12);
      m_row++;
     }

   //--- continuation line under a KV row, aligned to the value column
   void              Cont(const string val,const color clr)
     {
      Cell(m_row,11*m_cw,val,clr,m_cols-12);
      m_row++;
     }

   //--- one confluence factor across five aligned columns
   void              FactorRow(const string name,const string bar,const string score,
                               const string weight,const string note,const color clr)
     {
      Cell(m_row,0,          name,  clr,     18);
      Cell(m_row,19*m_cw,    bar,   clr,     10);
      Cell(m_row,30*m_cw,    score, clr,      6);
      Cell(m_row,37*m_cw,    weight,m_c_dim,  6);
      if(!m_compact && m_cols>50)
         Cell(m_row,45*m_cw, note,  m_c_dim, m_cols-46);
      m_row++;
     }

   void              DrawPanel(CMarketState *ms,CSmcEngine *eng,CConfluence *conf,CRiskManager *risk,
                               COnlineLearner *model,const SSignal &sig,const string mode,
                               const double threshold,const string last_action,const int open_positions,
                               const string news_line,const int gmt)
     {
      if(!m_draw_panel) return;
      //--- MetaTrader paints foreground objects in creation order, and the
      //--- chart layer is rebuilt after this panel was first created - so
      //--- order blocks, structure labels and liquidity text ended up drawn
      //--- across it. Rebuilding the whole panel each render makes it the
      //--- newest set of objects, and therefore always on top. Within the
      //--- rebuild the background is created first so the rows sit on it.
      DeleteGroup("P_");
      m_row=0;
      int W=m_cols;
      Panel("P_BG",m_x,m_y,m_width,m_last_rows*m_row_h+12,m_c_panel,C'60,64,74');
      datetime utc=SmcServerToUtc(SmcNow(),gmt);

      //--- title ------------------------------------------------------
      Row(Fit(StringFormat("%s v%s  %s %s  %s",SMC_AGENT_NAME,SMC_AGENT_VERSION,ms.Symbol(),
          EnumToString(ms.TfEntry()),TimeToString(SmcNow(),TIME_DATE|TIME_MINUTES)),W),m_c_accent);

      color mode_c=(mode=="LIVE"?m_c_bull:(mode=="LOCKED"?m_c_bear:m_c_accent));
      KV("MODE",StringFormat("%-8s  %s  acc %.0f%%  accept %.0f%%",mode,
         (model.IsWarm()?"model trained":StringFormat("warm-up %d/%d",(int)model.Updates(),model.WarmupNeeded())),
         model.Accuracy()*100.0,threshold*100.0),mode_c);

      int pc=SmcPcGmtOffsetHours();
      KV("CLOCKS",StringFormat("srv %s GMT%+d | LDN %s | NY %s | you %s",
         TimeToString(SmcNow(),TIME_MINUTES),gmt,
         SmcHm(SmcZoneHourF(TZ_LONDON,utc)),SmcHm(SmcZoneHourF(TZ_NY,utc)),
         (pc==99?"tz?":SmcHm(SmcPcHourF(utc)))),m_c_dim);

      //--- market -----------------------------------------------------
      Row(Rule("MARKET",W),m_c_dim);
      KV("BIAS",StringFormat("%s %s | %s %s | entry %s / int %s",
         EnumToString(ms.TfHigh()),SmcDirStr(conf.BiasHtf()),
         EnumToString(ms.TfMid()),SmcDirStr(conf.BiasMid()),
         SmcDirStr(eng.Trend()),SmcDirStr(eng.InternalTrend())),m_c_text);

      double hi,lo;
      if(eng.Range(hi,lo))
        {
         double pos=eng.RangePosition(SymbolInfoDouble(ms.Symbol(),SYMBOL_BID))*100.0;
         KV("RANGE",StringFormat("%.2f - %.2f   price %.0f%% (%s)",lo,hi,pos,(pos>50.0?"premium":"discount")),m_c_dim);
        }
      else KV("RANGE","not mapped yet",m_c_dim);

      KV("RAID",(eng.SweepValid()
         ?StringFormat("%s %s %d bars ago  quality %.2f",eng.SweepPool(),SmcDirStr(eng.SweepDir()),
                       eng.SweepAge(),eng.SweepQuality())
         :"none in the current window"),
         (eng.SweepValid()?(eng.SweepDir()==DIR_BULL?m_c_bull:m_c_bear):m_c_dim));

      KV("PLAYBOOK",conf.Playbook(),m_c_text);

      //--- confluence -------------------------------------------------
      Row(Rule("CONFLUENCE",W),m_c_dim);
      FactorRow("FACTOR","  -   +   ","SCORE","WEIGHT","READING",m_c_dim);

      double total=0.0;
      for(int i=0;i<F_COUNT;i++)
        {
         SFactor f;
         if(!conf.GetFactor(i,f)) continue;
         total+=f.contrib;
         color c=(f.score>0.15?m_c_bull:(f.score<-0.15?m_c_bear:m_c_dim));
         FactorRow(f.name,Bar(f.score,4),
                   StringFormat("%+0.2f",f.score),
                   StringFormat("%+0.2f",f.weight),f.note,c);
        }

      color sc=(total>0?m_c_bull:m_c_bear);
      KV("SCORE",StringFormat("%+0.3f weighted  ->  probability %s  (bias %+0.2f)",
         total,(sig.prob>0.0?StringFormat("%.1f%%",sig.prob*100.0):"n/a"),model.Bias()),sc);

      //--- risk -------------------------------------------------------
      Row(Rule("RISK",W),m_c_dim);
      double dp=risk.DayPnLPct();
      color dc=(dp>=0.0?m_c_bull:(dp<-2.0?m_c_bear:m_c_accent));
      KV(StringFormat("FTMO P%d",risk.Phase()),
         StringFormat("day %+0.2f%%  total %+0.2f%%  target %.0f%%  days %d/%d",
         dp,risk.TotalPnLPct(),risk.TargetProgress()*100.0,risk.TradingDays(),risk.MinDays()),dc);
      KV("FLOORS",StringFormat("soft %.2f  hard %.2f  room %.0f / %.0f",
         risk.SoftDailyFloor(),risk.HardDailyFloor(),
         risk.RemainingDailyBudget(),risk.RemainingHardBudget()),m_c_dim);
      KV("CAPITAL",StringFormat("%.2f (%s)  eq %.2f  open risk %.0f",
         risk.Initial(),risk.CapitalSource(),AccountInfoDouble(ACCOUNT_EQUITY),risk.OpenRiskMoney()),m_c_dim);
      KV("NEWS",news_line,m_c_dim);

      //--- decision ---------------------------------------------------
      Row(Rule("DECISION",W),m_c_dim);
      if(sig.valid)
        {
         color c=(sig.dir==DIR_BULL?m_c_bull:m_c_bear);
         KV("SIGNAL",StringFormat("%s  entry %.2f  sl %.2f  tp %.2f (%.2fR)",
            SmcDirShort(sig.dir),sig.entry,sig.sl,sig.tp1,sig.rr1),c);
        }
      else
        {
         string v=conf.Veto();
         KV("SIGNAL","none - "+(v==""?"no qualified setup on this close":v),m_c_dim);
        }

      string wrapped[];
      int nl=Wrap(conf.Context(),m_cols-12,3,wrapped);
      for(int i=0;i<nl;i++)
        {
         if(i==0) KV("READING",wrapped[i],m_c_text);
         else     Cont(wrapped[i],m_c_text);
        }

      KV("ACTION",StringFormat("%s   open %d",last_action,open_positions),m_c_accent);

      int used=m_row;
      m_last_rows=used;
      Panel("P_BG",m_x,m_y,m_width,used*m_row_h+12,m_c_panel,C'60,64,74');
      ChartRedraw(m_chart);
     }
  };

#endif // __SMC_VISUALS_MQH__
