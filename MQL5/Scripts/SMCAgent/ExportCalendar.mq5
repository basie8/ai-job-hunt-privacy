//+------------------------------------------------------------------+
//|                                            ExportCalendar.mq5    |
//|                                                                  |
//|  Write the MT5 economic calendar out as smc_news.csv so the       |
//|  agent has real news in the Strategy Tester.                      |
//|                                                                  |
//|  The problem this solves: CalendarValueHistory() is often not     |
//|  served inside the tester, so a backtest silently runs with no    |
//|  news handling. WebRequest() does not work there either, which is |
//|  why fetching a third party feed at runtime would not help. But   |
//|  the calendar IS available on a live chart - so export it once    |
//|  here, and the agent's CSV fallback reads it during the test.     |
//|                                                                  |
//|  Run this on any chart of a live (or demo) terminal that is       |
//|  logged in. It writes to the COMMON files folder, which is where  |
//|  the agent looks:                                                 |
//|      %APPDATA%\MetaQuotes\Terminal\Common\Files\smc_news.csv      |
//|                                                                  |
//|  Format, one event per line, semicolon separated:                 |
//|      YYYY.MM.DD HH:MM ; CUR ; importance 1-3 ; event name         |
//|  Timestamps are GMT, matching what the agent expects.             |
//+------------------------------------------------------------------+
#property copyright "SMC AI Agent"
#property version   "1.00"
#property script_show_inputs
#property description "Exports the MT5 economic calendar to smc_news.csv for backtesting."

input datetime InpFrom       = D'2023.01.01 00:00';  // Export events from
input datetime InpTo         = D'2026.12.31 00:00';  // Export events to
input string   InpCurrencies = "USD,EUR,GBP";        // Currencies, comma separated
input int      InpMinImp     = 1;                    // Minimum importance to keep (1 low, 2 mid, 3 high)
input string   InpFile       = "smc_news.csv";       // Output file in the COMMON folder

//+------------------------------------------------------------------+
int ImportanceOf(const ENUM_CALENDAR_EVENT_IMPORTANCE imp)
  {
   if(imp==CALENDAR_IMPORTANCE_HIGH)     return(3);
   if(imp==CALENDAR_IMPORTANCE_MODERATE) return(2);
   if(imp==CALENDAR_IMPORTANCE_LOW)      return(1);
   return(0);                                   // NONE - not a scheduled release
  }

//--- the agent splits on ';', so a name containing one would corrupt the row
string Sanitise(string s)
  {
   StringReplace(s,";",",");
   StringReplace(s,"\n"," ");
   StringReplace(s,"\r"," ");
   return(s);
  }

//+------------------------------------------------------------------+
void OnStart()
  {
   if(InpTo<=InpFrom)
     { Print("ExportCalendar: the end date must be after the start date."); return; }

   string cur[];
   int nc=StringSplit(InpCurrencies,',',cur);
   if(nc<=0)
     { Print("ExportCalendar: no currencies given."); return; }
   for(int i=0;i<nc;i++)
     {
      StringTrimLeft(cur[i]);
      StringTrimRight(cur[i]);
      StringToUpper(cur[i]);
     }

   int h=FileOpen(InpFile,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h==INVALID_HANDLE)
     { PrintFormat("ExportCalendar: cannot write %s (error %d).",InpFile,GetLastError()); return; }

   FileWriteString(h,"# smc_news.csv - exported from the MT5 economic calendar\r\n");
   FileWriteString(h,StringFormat("# generated %s covering %s to %s\r\n",
                   TimeToString(TimeCurrent(),TIME_DATE|TIME_MINUTES),
                   TimeToString(InpFrom,TIME_DATE),TimeToString(InpTo,TIME_DATE)));
   FileWriteString(h,"# GMT time ; currency ; importance 1-3 ; event\r\n");

   int written=0,skipped=0;
   for(int c=0;c<nc;c++)
     {
      MqlCalendarValue values[];
      int cnt=CalendarValueHistory(values,InpFrom,InpTo,NULL,cur[c]);
      if(cnt<=0)
        {
         PrintFormat("ExportCalendar: %s returned no events (error %d). Is the calendar downloaded in this terminal?",
                     cur[c],GetLastError());
         continue;
        }
      for(int i=0;i<cnt;i++)
        {
         MqlCalendarEvent ev;
         if(!CalendarEventById(values[i].event_id,ev)) { skipped++; continue; }
         int imp=ImportanceOf(ev.importance);
         if(imp<InpMinImp || imp<=0) { skipped++; continue; }
         //--- calendar values are GMT, and that is what the agent expects
         FileWriteString(h,StringFormat("%s;%s;%d;%s\r\n",
                         TimeToString(values[i].time,TIME_DATE|TIME_MINUTES),
                         cur[c],imp,Sanitise(ev.name)));
         written++;
        }
      PrintFormat("ExportCalendar: %s - %d events read",cur[c],cnt);
     }
   FileClose(h);

   if(written==0)
     {
      Print("ExportCalendar: nothing was written. The calendar is empty in this terminal - open Toolbox > Calendar once to make it download, then run this again.");
      return;
     }
   PrintFormat("ExportCalendar: wrote %d events to the common folder as %s (%d skipped as below importance %d).",
               written,InpFile,skipped,InpMinImp);
   Print("ExportCalendar: the agent will now pick this up in the Strategy Tester as its CSV fallback.");
  }
