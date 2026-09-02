//+------------------------------------------------------------------+
//|                                                   NewsFilter.mqh |
//|                                                                  |
//|  Major news handling for XAUUSD.                                 |
//|  Gold is a macro instrument: CPI / NFP / FOMC / PPI / GDP and     |
//|  central bank speeches move it more than any chart pattern, and   |
//|  FTMO funded accounts forbid opening or closing inside a 2 minute |
//|  window around high impact releases. The agent therefore:         |
//|    - blocks new entries inside a release window,                  |
//|    - de-risks open exposure before a release,                     |
//|    - and then hunts the post-release liquidity raid, which is     |
//|      the highest quality SMC setup of the day.                    |
//+------------------------------------------------------------------+
#ifndef __SMC_NEWSFILTER_MQH__
#define __SMC_NEWSFILTER_MQH__

#include "Defs.mqh"
#include "Logger.mqh"

struct SNewsEvent
  {
   datetime          time;
   string            name;
   string            currency;
   int               importance;   // 1 = low, 2 = moderate, 3 = high
  };

class CNewsFilter
  {
private:
   SNewsEvent        m_events[];
   datetime          m_last_refresh;
   bool              m_available;
   bool              m_use_csv;
   string            m_csv;
   string            m_currencies[];
   CLogger          *m_log;
   int               m_gmt;        // server-time minus GMT, supplied by the agent

   bool              CurrencyWatched(const string cur)
     {
      for(int i=0;i<ArraySize(m_currencies);i++)
         if(m_currencies[i]==cur) return(true);
      return(false);
     }

   void              Push(const datetime t,const string name,const string cur,const int imp)
     {
      int n=ArraySize(m_events);
      ArrayResize(m_events,n+1);
      m_events[n].time=t;
      m_events[n].name=name;
      m_events[n].currency=cur;
      m_events[n].importance=imp;
     }

   void              SortEvents(void)
     {
      int n=ArraySize(m_events);
      for(int i=1;i<n;i++)
        {
         SNewsEvent key=m_events[i];
         int j=i-1;
         while(j>=0 && m_events[j].time>key.time) { m_events[j+1]=m_events[j]; j--; }
         m_events[j+1]=key;
        }
     }

   bool              LoadFromCalendar(const datetime from,const datetime to)
     {
      MqlCalendarValue values[];
      int total=0;
      for(int c=0;c<ArraySize(m_currencies);c++)
        {
         ArrayFree(values);
         int cnt=CalendarValueHistory(values,from,to,NULL,m_currencies[c]);
         if(cnt<=0) continue;
         for(int i=0;i<cnt;i++)
           {
            MqlCalendarEvent ev;
            if(!CalendarEventById(values[i].event_id,ev)) continue;
            int imp=1;
            if(ev.importance==CALENDAR_IMPORTANCE_HIGH)     imp=3;
            else if(ev.importance==CALENDAR_IMPORTANCE_MODERATE) imp=2;
            else if(ev.importance==CALENDAR_IMPORTANCE_LOW) imp=1;
            else continue;                                    // importance NONE -> ignore
            //--- MT5 publishes calendar values in GMT; every timestamp the
            //--- agent works with is server time, so convert once here
            datetime srv=values[i].time+(datetime)(m_gmt*3600);
            Push(srv,ev.name,m_currencies[c],imp);
            total++;
           }
        }
      return(total>0);
     }

   bool              LoadFromCsv(void)
     {
      int h=FileOpen(m_csv,FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
      if(h==INVALID_HANDLE) return(false);
      int total=0;
      while(!FileIsEnding(h))
        {
         string line=FileReadString(h);
         if(StringLen(line)<10) continue;
         if(StringGetCharacter(line,0)=='#') continue;
         string parts[];
         int k=StringSplit(line,';',parts);
         if(k<4) continue;
         //--- CSV timestamps follow the same convention as the MT5
         //--- calendar: they are GMT and are converted to server time here
         datetime t=StringToTime(parts[0]);
         if(t<=0) continue;
         t+=(datetime)(m_gmt*3600);
         string cur=parts[1];
         int imp=(int)StringToInteger(parts[2]);
         if(!CurrencyWatched(cur)) continue;
         Push(t,parts[3],cur,imp);
         total++;
        }
      FileClose(h);
      return(total>0);
     }

public:
                     CNewsFilter(void): m_last_refresh(0), m_available(false), m_use_csv(false),
                                        m_csv("smc_news.csv"), m_log(NULL), m_gmt(0) {}

   void              Init(const string symbol,CLogger *log,const int gmt_offset,
                          const string csv_fallback="smc_news.csv")
     {
      m_log=log;
      m_gmt=gmt_offset;
      m_csv=csv_fallback;
      //--- gold is priced in USD and reacts to USD macro first;
      //--- EUR / GBP releases move the dollar index as well.
      ArrayResize(m_currencies,3);
      m_currencies[0]="USD";
      m_currencies[1]="EUR";
      m_currencies[2]="GBP";
      //--- if the symbol carries an explicit currency pair, honour it
      string s=symbol;
      StringToUpper(s);
      if(StringFind(s,"XAU")<0 && StringLen(s)>=6)
        {
         m_currencies[0]=StringSubstr(s,0,3);
         m_currencies[1]=StringSubstr(s,3,3);
         ArrayResize(m_currencies,2);
        }
     }

   int               GmtOffset(void) const { return(m_gmt); }

   //--- the agent re-detects the broker offset every day; a change
   //--- (daylight saving) invalidates every cached event time
   bool              SetGmtOffset(const int gmt_offset)
     {
      if(gmt_offset==m_gmt) return(false);
      if(m_log!=NULL)
         m_log.Warn(StringFormat("News: server offset changed GMT%+d -> GMT%+d, reloading the calendar",m_gmt,gmt_offset));
      m_gmt=gmt_offset;
      Refresh(true);
      return(true);
     }

   bool              Available(void) const { return(m_available); }
   bool              UsingCsv(void)  const { return(m_use_csv);   }
   int               Count(void)           { return(ArraySize(m_events)); }

   void              Refresh(const bool force=false)
     {
      datetime now=SmcNow();
      if(!force && m_last_refresh>0 && now-m_last_refresh<3600) return;
      m_last_refresh=now;
      ArrayFree(m_events);
      m_use_csv=false;

      datetime from=now-3*86400;
      datetime to  =now+10*86400;
      bool ok=false;
      ResetLastError();
      ok=LoadFromCalendar(from,to);
      if(!ok)
        {
         //--- calendar is not served (strategy tester, some brokers):
         //--- fall back to a user maintained CSV in the common folder
         ok=LoadFromCsv();
         m_use_csv=ok;
        }
      m_available=ok;
      SortEvents();
      if(m_log!=NULL)
        {
         if(ok) m_log.Info(StringFormat("News: %d events loaded (%s)",ArraySize(m_events),m_use_csv?"CSV fallback":"MT5 calendar"));
         else   m_log.Warn("News: no calendar data available - news guard degraded to time-of-day protection");
        }
     }

   //--- is 'when' inside [event - before, event + after] ? ------------
   bool              InBlackout(const datetime when,const int min_before,const int min_after,
                                const int min_importance,string &ev_name,int &minutes_to)
     {
      int n=ArraySize(m_events);
      for(int i=0;i<n;i++)
        {
         if(m_events[i].importance<min_importance) continue;
         long diff=(long)m_events[i].time-(long)when;      // >0 = event in the future
         if(diff<=(long)min_before*60 && diff>=-(long)min_after*60)
           {
            ev_name=m_events[i].name+" ("+m_events[i].currency+")";
            minutes_to=(int)(diff/60);
            return(true);
           }
        }
      ev_name=""; minutes_to=0;
      return(false);
     }

   //--- next event of at least the given importance -------------------
   bool              NextEvent(const datetime when,const int min_importance,SNewsEvent &out,int &minutes)
     {
      int n=ArraySize(m_events);
      for(int i=0;i<n;i++)
        {
         if(m_events[i].importance<min_importance) continue;
         if(m_events[i].time>=when)
           {
            out=m_events[i];
            minutes=(int)(((long)m_events[i].time-(long)when)/60);
            return(true);
           }
        }
      return(false);
     }

   //--- a high impact release that fired within the last X minutes ----
   bool              JustReleased(const datetime when,const int within_minutes,const int min_importance,SNewsEvent &out)
     {
      int n=ArraySize(m_events);
      bool found=false;
      for(int i=0;i<n;i++)
        {
         if(m_events[i].importance<min_importance) continue;
         long age=(long)when-(long)m_events[i].time;
         if(age>=0 && age<=(long)within_minutes*60) { out=m_events[i]; found=true; }
        }
      return(found);
     }

   string            Describe(const datetime when,const int min_importance)
     {
      SNewsEvent e;
      int mins=0;
      if(NextEvent(when,min_importance,e,mins))
         return(StringFormat("%s %s in %dm",e.currency,e.name,mins));
      return("no scheduled high impact event");
     }
  };

#endif // __SMC_NEWSFILTER_MQH__
