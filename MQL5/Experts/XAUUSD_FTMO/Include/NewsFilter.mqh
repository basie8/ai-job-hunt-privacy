//+------------------------------------------------------------------+
//|                                                   NewsFilter.mqh |
//|  High-impact news blackout for FTMO compliance.                  |
//|                                                                  |
//|  Three independent sources, any combination:                     |
//|    1. ForexFactory weekly feed (nfs.faireconomy.media JSON)      |
//|    2. The MT5 terminal's built-in economic calendar              |
//|    3. A manual CSV file the trader maintains by hand             |
//|                                                                  |
//|  The ForexFactory feed needs the host whitelisted under          |
//|  Tools > Options > Expert Advisors > Allow WebRequest for URL.   |
//|  WebRequest is unavailable in the Strategy Tester, so in tester  |
//|  runs the module silently falls back to the MT5 calendar.        |
//+------------------------------------------------------------------+
#ifndef __XAUUSD_FTMO_NEWSFILTER_MQH__
#define __XAUUSD_FTMO_NEWSFILTER_MQH__

#include "CoreDefs.mqh"

#define FF_FEED_URL       "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
#define FF_CACHE_FILE     "XAUUSD_FTMO_ff_calendar.json"
#define NEWS_MAX_EVENTS   2048

//+------------------------------------------------------------------+
//| CNewsFilter                                                      |
//+------------------------------------------------------------------+
class CNewsFilter
  {
private:
   NewsEvent         m_events[];
   int               m_count;

   ENUM_NEWS_SOURCE  m_source;
   string            m_currencies;        // e.g. "USD,EUR,XAU,ALL"
   int               m_minutesBefore;
   int               m_minutesAfter;
   bool              m_includeMedium;
   int               m_gmtOffsetSec;      // server time = GMT + offset
   int               m_refreshMinutes;
   string            m_manualCsv;
   bool              m_verbose;

   datetime          m_lastFetch;
   bool              m_ffAvailable;
   bool              m_calendarAvailable;
   string            m_lastError;

   // blackout state cached for the dashboard
   bool              m_inBlackout;
   string            m_blackoutTitle;
   datetime          m_blackoutTime;
   datetime          m_blackoutEnds;

   //--- helpers
   bool              CurrencyWatched(const string ccy) const;
   void              AddEvent(const datetime t, const int impact, const string ccy, const string title);
   void              SortEvents(void);
   bool              FetchForexFactory(void);
   bool              LoadFromCache(void);
   bool              SaveToCache(const string body);
   int               ParseForexFactoryJson(const string body);
   bool              LoadMt5Calendar(void);
   bool              LoadManualCsv(void);
   static string     JsonStringValue(const string chunk, const string key);
   static datetime   ParseIso8601(const string iso, const int serverGmtOffsetSec);
   static int        ImpactFromText(const string text);

public:
                     CNewsFilter(void);

   bool              Init(const ENUM_NEWS_SOURCE source,
                          const string currencies,
                          const int minutesBefore,
                          const int minutesAfter,
                          const bool includeMedium,
                          const int gmtOffsetSec,
                          const int refreshMinutes,
                          const string manualCsv,
                          const bool verbose);

   void              Refresh(const bool force = false);

   //--- true when 'now' sits inside a blackout window
   bool              IsBlackout(const datetime now);
   //--- true when a blackout starts within 'minutes' from now (used to flatten early)
   bool              BlackoutStartsWithin(const datetime now, const int minutes);

   int               EventCount(void)      const { return m_count; }
   bool              FeedHealthy(void)     const { return (m_ffAvailable || m_calendarAvailable || m_count > 0); }
   string            LastError(void)       const { return m_lastError; }
   string            BlackoutTitle(void)   const { return m_blackoutTitle; }
   datetime          BlackoutEnds(void)    const { return m_blackoutEnds; }
   string            NextEventText(const datetime now);
   void              SetGmtOffset(const int sec)  { m_gmtOffsetSec = sec; }
  };

//+------------------------------------------------------------------+
CNewsFilter::CNewsFilter(void)
  {
   m_count             = 0;
   m_source            = NEWS_SRC_BOTH;
   m_currencies        = "USD,XAU,ALL";
   m_minutesBefore     = 30;
   m_minutesAfter      = 30;
   m_includeMedium     = false;
   m_gmtOffsetSec      = 0;
   m_refreshMinutes    = 240;
   m_manualCsv         = "";
   m_verbose           = false;
   m_lastFetch         = 0;
   m_ffAvailable       = false;
   m_calendarAvailable = false;
   m_lastError         = "";
   m_inBlackout        = false;
   m_blackoutTitle     = "";
   m_blackoutTime      = 0;
   m_blackoutEnds      = 0;
   ArrayResize(m_events, 0);
  }

//+------------------------------------------------------------------+
bool CNewsFilter::Init(const ENUM_NEWS_SOURCE source,
                       const string currencies,
                       const int minutesBefore,
                       const int minutesAfter,
                       const bool includeMedium,
                       const int gmtOffsetSec,
                       const int refreshMinutes,
                       const string manualCsv,
                       const bool verbose)
  {
   m_source         = source;
   m_currencies     = currencies;
   StringToUpper(m_currencies);
   m_minutesBefore  = MathMax(0, minutesBefore);
   m_minutesAfter   = MathMax(0, minutesAfter);
   m_includeMedium  = includeMedium;
   m_gmtOffsetSec   = gmtOffsetSec;
   m_refreshMinutes = MathMax(15, refreshMinutes);
   m_manualCsv      = manualCsv;
   m_verbose        = verbose;

   if(m_source == NEWS_SRC_OFF)
     {
      PrintFormat("[News] DISABLED. This is not FTMO compliant - enable a source before going live.");
      return true;
     }

   Refresh(true);

   if(!FeedHealthy())
      PrintFormat("[News] WARNING: no calendar source produced any events. %s", m_lastError);

   return true;
  }

//+------------------------------------------------------------------+
//| Rebuilds the event table from every enabled source.              |
//+------------------------------------------------------------------+
void CNewsFilter::Refresh(const bool force)
  {
   if(m_source == NEWS_SRC_OFF)
      return;

   datetime now = TimeTradeServer();
   if(!force && m_lastFetch > 0 && (now - m_lastFetch) < m_refreshMinutes * 60)
      return;

   m_count = 0;
   ArrayResize(m_events, 0);
   m_lastError = "";

   bool wantFF  = (m_source == NEWS_SRC_FOREXFACTORY || m_source == NEWS_SRC_BOTH);
   bool wantMt5 = (m_source == NEWS_SRC_MT5 || m_source == NEWS_SRC_BOTH);

   if(wantFF)
     {
      if(MQLInfoInteger(MQL_TESTER))
        {
         // WebRequest is not available in the tester - use the cached file if
         // one exists, otherwise lean on the MT5 calendar.
         if(!LoadFromCache())
            m_lastError += "FF: tester mode, no cache. ";
        }
      else
        {
         if(!FetchForexFactory())
           {
            if(!LoadFromCache())
               m_lastError += "FF: fetch failed and no cache. ";
           }
        }
     }

   if(wantMt5)
     {
      if(!LoadMt5Calendar())
         m_lastError += "MT5 calendar unavailable. ";
     }

   LoadManualCsv();

   SortEvents();
   m_lastFetch = now;

   if(m_verbose)
      PrintFormat("[News] refreshed: %d events in table (FF=%s, MT5cal=%s)",
                  m_count,
                  (m_ffAvailable ? "ok" : "no"),
                  (m_calendarAvailable ? "ok" : "no"));
  }

//+------------------------------------------------------------------+
bool CNewsFilter::CurrencyWatched(const string ccy) const
  {
   // empty list or an explicit wildcard means "block on everything"
   if(StringLen(m_currencies) == 0)
      return true;
   if(StringFind(m_currencies, "*") >= 0)
      return true;

   string up = ccy;
   StringToUpper(up);

   // an event with no currency attached (some gold and geopolitical entries)
   // is treated as relevant - the safe default for a funded account
   if(StringLen(up) == 0)
      return true;

   return (StringFind(m_currencies, up) >= 0);
  }

//+------------------------------------------------------------------+
void CNewsFilter::AddEvent(const datetime t, const int impact, const string ccy, const string title)
  {
   if(t <= 0)
      return;
   if(m_count >= NEWS_MAX_EVENTS)
      return;

   int minImpact = (m_includeMedium ? NEWS_IMPACT_MEDIUM : NEWS_IMPACT_HIGH);
   if(impact < minImpact)
      return;
   if(!CurrencyWatched(ccy))
      return;

   // de-duplicate: same currency within 60s and same impact is the same event
   for(int i = 0; i < m_count; i++)
     {
      if(m_events[i].currency == ccy && MathAbs((double)(m_events[i].time - t)) < 60.0)
         return;
     }

   ArrayResize(m_events, m_count + 1);
   m_events[m_count].time     = t;
   m_events[m_count].impact   = impact;
   m_events[m_count].currency = ccy;
   m_events[m_count].title    = title;
   m_count++;
  }

//+------------------------------------------------------------------+
void CNewsFilter::SortEvents(void)
  {
   for(int i = 1; i < m_count; i++)
     {
      NewsEvent key = m_events[i];
      int j = i - 1;
      while(j >= 0 && m_events[j].time > key.time)
        {
         m_events[j + 1] = m_events[j];
         j--;
        }
      m_events[j + 1] = key;
     }
  }

//+------------------------------------------------------------------+
//| Downloads the ForexFactory weekly JSON feed.                     |
//| The feed is rate limited (2 downloads / 5 minutes) so the EA     |
//| only calls this every m_refreshMinutes and caches the body.      |
//+------------------------------------------------------------------+
bool CNewsFilter::FetchForexFactory(void)
  {
   char   post[];
   char   result[];
   string resultHeaders = "";
   string headers = "User-Agent: MetaTrader5\r\n";

   ArrayResize(post, 0);
   ResetLastError();

   int status = WebRequest("GET", FF_FEED_URL, headers, 8000, post, result, resultHeaders);

   if(status == -1)
     {
      int err = GetLastError();
      m_ffAvailable = false;
      if(err == 4014)
         m_lastError += "FF: URL not whitelisted (Tools>Options>Expert Advisors). ";
      else
         m_lastError += StringFormat("FF: WebRequest error %d. ", err);
      return false;
     }

   if(status != 200)
     {
      m_ffAvailable = false;
      m_lastError += StringFormat("FF: HTTP %d. ", status);
      return false;
     }

   string body = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   if(StringLen(body) < 32)
     {
      m_ffAvailable = false;
      m_lastError += "FF: empty body. ";
      return false;
     }

   int added = ParseForexFactoryJson(body);
   if(added >= 0)
     {
      SaveToCache(body);
      m_ffAvailable = true;
      return true;
     }

   m_ffAvailable = false;
   return false;
  }

//+------------------------------------------------------------------+
bool CNewsFilter::SaveToCache(const string body)
  {
   int h = FileOpen(FF_CACHE_FILE, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
      return false;
   FileWriteString(h, body);
   FileClose(h);
   return true;
  }

//+------------------------------------------------------------------+
bool CNewsFilter::LoadFromCache(void)
  {
   if(!FileIsExist(FF_CACHE_FILE))
      return false;
   int h = FileOpen(FF_CACHE_FILE, FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
      return false;
   string body = "";
   while(!FileIsEnding(h))
      body += FileReadString(h);
   FileClose(h);

   if(StringLen(body) < 32)
      return false;

   int added = ParseForexFactoryJson(body);
   if(added >= 0)
     {
      m_ffAvailable = true;
      return true;
     }
   return false;
  }

//+------------------------------------------------------------------+
//| Extracts the string value of "key" from a single JSON object.    |
//| The FF feed is flat (no nesting) so a scanner is enough and it   |
//| keeps the EA free of third party JSON libraries.                 |
//+------------------------------------------------------------------+
string CNewsFilter::JsonStringValue(const string chunk, const string key)
  {
   string needle = "\"" + key + "\"";
   int k = StringFind(chunk, needle);
   if(k < 0)
      return "";

   int colon = StringFind(chunk, ":", k + StringLen(needle));
   if(colon < 0)
      return "";

   int len = StringLen(chunk);
   int i = colon + 1;

   // skip whitespace
   while(i < len)
     {
      ushort c = StringGetCharacter(chunk, i);
      if(c != ' ' && c != '\t' && c != '\r' && c != '\n')
         break;
      i++;
     }
   if(i >= len)
      return "";

   ushort first = StringGetCharacter(chunk, i);
   if(first == '"')
     {
      int start = i + 1;
      int end = start;
      while(end < len)
        {
         ushort c = StringGetCharacter(chunk, end);
         if(c == '\\')
           {
            end += 2;
            continue;
           }
         if(c == '"')
            break;
         end++;
        }
      if(end >= len)
         return "";
      return StringSubstr(chunk, start, end - start);
     }

   // unquoted literal (null / number)
   int start2 = i;
   int end2 = start2;
   while(end2 < len)
     {
      ushort c = StringGetCharacter(chunk, end2);
      if(c == ',' || c == '}' || c == ']')
         break;
      end2++;
     }
   string raw = StringSubstr(chunk, start2, end2 - start2);
   StringTrimLeft(raw);
   StringTrimRight(raw);
   return raw;
  }

//+------------------------------------------------------------------+
//| "High" / "Medium" / "Low" / "Holiday" -> NEWS_IMPACT_*           |
//+------------------------------------------------------------------+
int CNewsFilter::ImpactFromText(const string text)
  {
   string t = text;
   StringToUpper(t);
   if(StringFind(t, "HIGH") >= 0 || StringFind(t, "RED") >= 0)
      return NEWS_IMPACT_HIGH;
   if(StringFind(t, "MEDIUM") >= 0 || StringFind(t, "MODERATE") >= 0 || StringFind(t, "ORANGE") >= 0)
      return NEWS_IMPACT_MEDIUM;
   if(StringFind(t, "LOW") >= 0 || StringFind(t, "YELLOW") >= 0)
      return NEWS_IMPACT_LOW;
   return NEWS_IMPACT_NONE;   // "Holiday" and "Non-Economic" land here
  }

//+------------------------------------------------------------------+
//| ISO 8601 -> broker server time.                                  |
//| Handles "2026-08-18T08:30:00-04:00", "...Z" and "... +00:00".    |
//+------------------------------------------------------------------+
datetime CNewsFilter::ParseIso8601(const string iso, const int serverGmtOffsetSec)
  {
   if(StringLen(iso) < 19)
      return 0;

   MqlDateTime dt;
   dt.year = (int)StringToInteger(StringSubstr(iso, 0, 4));
   dt.mon  = (int)StringToInteger(StringSubstr(iso, 5, 2));
   dt.day  = (int)StringToInteger(StringSubstr(iso, 8, 2));
   dt.hour = (int)StringToInteger(StringSubstr(iso, 11, 2));
   dt.min  = (int)StringToInteger(StringSubstr(iso, 14, 2));
   dt.sec  = (int)StringToInteger(StringSubstr(iso, 17, 2));
   dt.day_of_week = 0;
   dt.day_of_year = 0;

   if(dt.year < 1970 || dt.mon < 1 || dt.mon > 12 || dt.day < 1 || dt.day > 31)
      return 0;

   datetime local = StructToTime(dt);

   // trailing timezone designator
   int tzOffsetSec = 0;
   int len = StringLen(iso);
   if(len >= 20)
     {
      string tail = StringSubstr(iso, 19);
      StringTrimLeft(tail);
      StringTrimRight(tail);

      if(StringLen(tail) > 0)
        {
         ushort c0 = StringGetCharacter(tail, 0);
         if(c0 == 'Z' || c0 == 'z')
           {
            tzOffsetSec = 0;
           }
         else
            if(c0 == '+' || c0 == '-')
              {
               string rest = StringSubstr(tail, 1);
               StringReplace(rest, ":", "");
               if(StringLen(rest) >= 2)
                 {
                  int oh = (int)StringToInteger(StringSubstr(rest, 0, 2));
                  int om = (StringLen(rest) >= 4 ? (int)StringToInteger(StringSubstr(rest, 2, 2)) : 0);
                  tzOffsetSec = oh * 3600 + om * 60;
                  if(c0 == '-')
                     tzOffsetSec = -tzOffsetSec;
                 }
              }
        }
     }

   datetime utc = local - (datetime)tzOffsetSec;
   return utc + (datetime)serverGmtOffsetSec;
  }

//+------------------------------------------------------------------+
//| Walks the flat JSON array and adds every qualifying event.       |
//| Returns the number added, or -1 when the body is not parseable.  |
//+------------------------------------------------------------------+
int CNewsFilter::ParseForexFactoryJson(const string body)
  {
   int len = StringLen(body);
   if(len < 32)
      return -1;

   int added = 0;
   int pos = 0;
   int guard = 0;

   while(pos < len && guard < NEWS_MAX_EVENTS * 4)
     {
      guard++;
      int open = StringFind(body, "{", pos);
      if(open < 0)
         break;
      int close = StringFind(body, "}", open);
      if(close < 0)
         break;

      string chunk = StringSubstr(body, open, close - open + 1);
      pos = close + 1;

      string impactTxt = JsonStringValue(chunk, "impact");
      if(StringLen(impactTxt) == 0)
         continue;

      int impact = ImpactFromText(impactTxt);
      if(impact == NEWS_IMPACT_NONE)
         continue;

      // the FF feed labels the column "country" but ships currency codes
      string ccy = JsonStringValue(chunk, "country");
      if(StringLen(ccy) == 0)
         ccy = JsonStringValue(chunk, "currency");
      StringToUpper(ccy);

      string dateTxt = JsonStringValue(chunk, "date");
      if(StringLen(dateTxt) == 0)
         continue;

      datetime evTime = ParseIso8601(dateTxt, m_gmtOffsetSec);
      if(evTime <= 0)
         continue;

      string title = JsonStringValue(chunk, "title");

      int before = m_count;
      AddEvent(evTime, impact, ccy, title);
      if(m_count > before)
         added++;
     }

   return added;
  }

//+------------------------------------------------------------------+
//| Reads the terminal's own economic calendar.                      |
//| Available from build 2005 upward; some brokers ship it empty,    |
//| in which case the ForexFactory feed carries the filter.          |
//+------------------------------------------------------------------+
bool CNewsFilter::LoadMt5Calendar(void)
  {
   MqlCalendarValue values[];
   datetime from = TimeTradeServer() - 2 * PeriodSeconds(PERIOD_D1);
   datetime to   = TimeTradeServer() + 8 * PeriodSeconds(PERIOD_D1);

   ResetLastError();
   int total = CalendarValueHistory(values, from, to, NULL, NULL);

   if(total <= 0)
     {
      m_calendarAvailable = false;
      return false;
     }

   int added = 0;
   for(int i = 0; i < total; i++)
     {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev))
         continue;

      int impact = NEWS_IMPACT_NONE;
      if(ev.importance == CALENDAR_IMPORTANCE_HIGH)
         impact = NEWS_IMPACT_HIGH;
      else
         if(ev.importance == CALENDAR_IMPORTANCE_MODERATE)
            impact = NEWS_IMPACT_MEDIUM;
         else
            if(ev.importance == CALENDAR_IMPORTANCE_LOW)
               impact = NEWS_IMPACT_LOW;

      if(impact == NEWS_IMPACT_NONE)
         continue;

      MqlCalendarCountry country;
      string ccy = "";
      if(CalendarCountryById(ev.country_id, country))
         ccy = country.currency;
      StringToUpper(ccy);

      // calendar times are already trade-server time
      int before = m_count;
      AddEvent(values[i].time, impact, ccy, ev.name);
      if(m_count > before)
         added++;
     }

   m_calendarAvailable = true;
   return true;
  }

//+------------------------------------------------------------------+
//| Optional manual list: one event per line,                        |
//|   YYYY.MM.DD HH:MM,CCY,IMPACT,Title                              |
//| Times are broker server time. Useful for a hand-curated list of  |
//| FOMC / NFP / CPI dates when no feed is reachable.                |
//+------------------------------------------------------------------+
bool CNewsFilter::LoadManualCsv(void)
  {
   if(StringLen(m_manualCsv) == 0)
      return false;
   if(!FileIsExist(m_manualCsv))
      return false;

   int h = FileOpen(m_manualCsv, FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
      return false;

   while(!FileIsEnding(h))
     {
      string line = FileReadString(h);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringLen(line) == 0)
         continue;
      if(StringGetCharacter(line, 0) == '#')
         continue;

      string f[];
      int n = StringSplit(line, ',', f);
      if(n < 3)
         continue;

      datetime t = StringToTime(f[0]);
      if(t <= 0)
         continue;

      string ccy = f[1];
      StringTrimLeft(ccy);
      StringTrimRight(ccy);
      StringToUpper(ccy);

      int impact = ImpactFromText(f[2]);
      string title = (n >= 4 ? f[3] : "manual");

      AddEvent(t, impact, ccy, title);
     }

   FileClose(h);
   return true;
  }

//+------------------------------------------------------------------+
//| Blackout test. Returns true when trading must be suspended.      |
//+------------------------------------------------------------------+
bool CNewsFilter::IsBlackout(const datetime now)
  {
   m_inBlackout    = false;
   m_blackoutTitle = "";
   m_blackoutTime  = 0;
   m_blackoutEnds  = 0;

   if(m_source == NEWS_SRC_OFF)
      return false;

   for(int i = 0; i < m_count; i++)
     {
      datetime start = m_events[i].time - (datetime)(m_minutesBefore * 60);
      datetime end   = m_events[i].time + (datetime)(m_minutesAfter * 60);

      if(now >= start && now <= end)
        {
         m_inBlackout    = true;
         m_blackoutTitle = StringFormat("%s %s", m_events[i].currency, m_events[i].title);
         m_blackoutTime  = m_events[i].time;
         m_blackoutEnds  = end;
         return true;
        }
     }
   return false;
  }

//+------------------------------------------------------------------+
//| True when a blackout window opens within the next 'minutes'.     |
//+------------------------------------------------------------------+
bool CNewsFilter::BlackoutStartsWithin(const datetime now, const int minutes)
  {
   if(m_source == NEWS_SRC_OFF)
      return false;

   datetime horizon = now + (datetime)(minutes * 60);
   for(int i = 0; i < m_count; i++)
     {
      datetime start = m_events[i].time - (datetime)(m_minutesBefore * 60);
      if(start >= now && start <= horizon)
         return true;
     }
   return false;
  }

//+------------------------------------------------------------------+
string CNewsFilter::NextEventText(const datetime now)
  {
   for(int i = 0; i < m_count; i++)
     {
      if(m_events[i].time >= now)
        {
         int mins = (int)((m_events[i].time - now) / 60);
         return StringFormat("%s %s in %dm", m_events[i].currency, m_events[i].title, mins);
        }
     }
   return "none scheduled";
  }

#endif // __XAUUSD_FTMO_NEWSFILTER_MQH__
//+------------------------------------------------------------------+
