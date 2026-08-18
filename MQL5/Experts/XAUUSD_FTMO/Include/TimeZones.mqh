//+------------------------------------------------------------------+
//|                                                    TimeZones.mqh |
//|  Daylight-saving aware time alignment.                           |
//|                                                                  |
//|  WHY THIS FILE EXISTS                                            |
//|  ------------------------------------------------------------    |
//|  Three different clocks matter to this EA and none of them stay  |
//|  fixed relative to the others:                                   |
//|                                                                  |
//|    * the BROKER SERVER clock - FTMO's MT5 servers run on         |
//|      CE(S)T, so they jump GMT+2 -> GMT+3 on the last Sunday in   |
//|      March and back on the last Sunday in October;               |
//|    * the LONDON market clock - GMT -> BST on the same EU dates;  |
//|    * the NEW YORK market clock - EST -> EDT on the SECOND Sunday |
//|      in March and back on the FIRST Sunday in November.          |
//|                                                                  |
//|  The EU and US transition dates are about two weeks apart, so    |
//|  for roughly three weeks a year the London/NY relationship is    |
//|  one hour different from the rest of the year. A session window  |
//|  pinned to fixed GMT is therefore wrong for part of every year,  |
//|  and a news feed timestamped in US Eastern is wrong for a        |
//|  different part of it.                                           |
//|                                                                  |
//|  Everything here works in UTC and converts outward, which is the |
//|  only way to keep the three clocks consistent.                   |
//+------------------------------------------------------------------+
#ifndef __XAUUSD_FTMO_TIMEZONES_MQH__
#define __XAUUSD_FTMO_TIMEZONES_MQH__

#include "CoreDefs.mqh"

//--- the market clock a session's times are expressed in
enum ENUM_MARKET_TZ
  {
   MARKET_TZ_UTC     = 0,  // UTC / GMT (no DST)
   MARKET_TZ_LONDON  = 1,  // Europe/London   GMT / BST
   MARKET_TZ_NEWYORK = 2,  // America/New_York EST / EDT
   MARKET_TZ_TOKYO   = 3,  // Asia/Tokyo      JST (no DST)
   MARKET_TZ_CET     = 4   // Europe/Prague   CET / CEST  <- FTMO's day boundary
  };

//--- how the session time inputs should be read
enum ENUM_SESSION_TIMEBASE
  {
   SESSION_TB_MARKET_LOCAL = 0, // Local market time, DST aware (recommended)
   SESSION_TB_GMT          = 1, // Fixed GMT/UTC, ignores DST
   SESSION_TB_SERVER       = 2  // Literal broker server time
  };

//+------------------------------------------------------------------+
int TZ_DaysInMonth(const int year, const int month)
  {
   if(month < 1 || month > 12)
      return 30;

   int days[12] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
   int n = days[month - 1];

   if(month == 2)
     {
      bool leap = ((year % 4 == 0 && year % 100 != 0) || (year % 400 == 0));
      if(leap)
         n = 29;
     }
   return n;
  }

//+------------------------------------------------------------------+
//| Builds a UTC timestamp. MQL5's StructToTime is a plain calendar  |
//| conversion with no timezone applied, which is exactly what we    |
//| want as the neutral base.                                        |
//+------------------------------------------------------------------+
datetime TZ_MakeTime(const int year, const int mon, const int day,
                     const int hour, const int minute)
  {
   MqlDateTime s;
   s.year        = year;
   s.mon         = mon;
   s.day         = day;
   s.hour        = hour;
   s.min         = minute;
   s.sec         = 0;
   s.day_of_week = 0;
   s.day_of_year = 0;
   return StructToTime(s);
  }

//+------------------------------------------------------------------+
//| Day of week for a calendar date. 0 = Sunday.                     |
//+------------------------------------------------------------------+
int TZ_WeekdayOf(const int year, const int mon, const int day)
  {
   datetime t = TZ_MakeTime(year, mon, day, 12, 0);
   MqlDateTime s;
   TimeToStruct(t, s);
   return s.day_of_week;
  }

//+------------------------------------------------------------------+
//| Day-of-month of the LAST given weekday in a month.               |
//+------------------------------------------------------------------+
int TZ_LastWeekdayDay(const int year, const int mon, const int weekday)
  {
   int last = TZ_DaysInMonth(year, mon);
   for(int d = last; d >= 1; d--)
      if(TZ_WeekdayOf(year, mon, d) == weekday)
         return d;
   return last;
  }

//+------------------------------------------------------------------+
//| Day-of-month of the Nth given weekday in a month (n starts at 1).|
//+------------------------------------------------------------------+
int TZ_NthWeekdayDay(const int year, const int mon, const int weekday, const int n)
  {
   int count = 0;
   int last  = TZ_DaysInMonth(year, mon);
   for(int d = 1; d <= last; d++)
     {
      if(TZ_WeekdayOf(year, mon, d) == weekday)
        {
         count++;
         if(count == n)
            return d;
        }
     }
   return last;
  }

//+------------------------------------------------------------------+
//| EU summer time: last Sunday in March 01:00 UTC                   |
//|              -> last Sunday in October 01:00 UTC.                |
//| Governs London, CET, and therefore the FTMO server clock.        |
//+------------------------------------------------------------------+
bool TZ_IsEuSummerTime(const datetime utc)
  {
   MqlDateTime s;
   TimeToStruct(utc, s);
   int y = s.year;

   datetime start = TZ_MakeTime(y, 3,  TZ_LastWeekdayDay(y, 3,  0), 1, 0);
   datetime end   = TZ_MakeTime(y, 10, TZ_LastWeekdayDay(y, 10, 0), 1, 0);

   return (utc >= start && utc < end);
  }

//+------------------------------------------------------------------+
//| US summer time: second Sunday in March 02:00 local standard      |
//|              -> first Sunday in November 02:00 local daylight.   |
//| Expressed in UTC that is 07:00 and 06:00 respectively for the    |
//| US Eastern zone, which is the only US zone this EA cares about.  |
//+------------------------------------------------------------------+
bool TZ_IsUsSummerTime(const datetime utc)
  {
   MqlDateTime s;
   TimeToStruct(utc, s);
   int y = s.year;

   datetime start = TZ_MakeTime(y, 3,  TZ_NthWeekdayDay(y, 3,  0, 2), 7, 0);
   datetime end   = TZ_MakeTime(y, 11, TZ_NthWeekdayDay(y, 11, 0, 1), 6, 0);

   return (utc >= start && utc < end);
  }

//+------------------------------------------------------------------+
//| Offset of a market clock from UTC, in seconds, at the given      |
//| moment. Positive means ahead of UTC.                             |
//+------------------------------------------------------------------+
int TZ_MarketUtcOffsetSeconds(const ENUM_MARKET_TZ tz, const datetime utc)
  {
   switch(tz)
     {
      case MARKET_TZ_LONDON:
         return (TZ_IsEuSummerTime(utc) ? 3600 : 0);

      case MARKET_TZ_CET:
         return (TZ_IsEuSummerTime(utc) ? 7200 : 3600);

      case MARKET_TZ_NEWYORK:
         return (TZ_IsUsSummerTime(utc) ? -14400 : -18000);

      case MARKET_TZ_TOKYO:
         return 32400;                      // JST, no daylight saving

      default:
         return 0;
     }
  }

//+------------------------------------------------------------------+
string TZ_MarketName(const ENUM_MARKET_TZ tz)
  {
   switch(tz)
     {
      case MARKET_TZ_LONDON:  return "London";
      case MARKET_TZ_NEWYORK: return "New York";
      case MARKET_TZ_TOKYO:   return "Tokyo";
      case MARKET_TZ_CET:     return "CET";
      default:                return "UTC";
     }
  }

//+------------------------------------------------------------------+
//| Detects the broker's offset from GMT.                            |
//|                                                                  |
//| 'plausible' comes back false when the terminal cannot give a     |
//| usable answer (no connection, or the tester's simulated GMT),    |
//| in which case the manual value is returned and the caller should |
//| warn rather than trade on a guess.                               |
//+------------------------------------------------------------------+
int TZ_DetectServerGmtOffset(const int manualHours, const bool useManual, bool &plausible)
  {
   plausible = true;

   if(useManual)
      return manualHours * 3600;

   datetime srv = TimeTradeServer();
   datetime gmt = TimeGMT();

   if(srv <= 0 || gmt <= 0)
     {
      plausible = false;
      return manualHours * 3600;
     }

   // round to the nearest half hour to absorb clock jitter
   double diff      = (double)(srv - gmt);
   double halfHours = MathRound(diff / 1800.0);
   int    offset    = (int)(halfHours * 1800.0);

   // no real broker sits outside this band; anything else is a bad reading
   if(offset < -12 * 3600 || offset > 14 * 3600)
     {
      plausible = false;
      return manualHours * 3600;
     }

   return offset;
  }

//+------------------------------------------------------------------+
//| Converts a "HH:MM" session boundary into minutes-since-midnight  |
//| in BROKER SERVER time, honouring the chosen time base and the    |
//| DST state in force at 'utcNow'. Returns -1 when malformed.       |
//+------------------------------------------------------------------+
int TZ_SessionMinuteToServer(const string hhmm,
                             const ENUM_SESSION_TIMEBASE base,
                             const ENUM_MARKET_TZ tz,
                             const int serverGmtOffsetSec,
                             const datetime utcNow)
  {
   int m = ParseHHMM(hhmm);
   if(m < 0)
      return -1;

   if(base == SESSION_TB_SERVER)
      return m;

   int marketOffsetSec = 0;
   if(base == SESSION_TB_MARKET_LOCAL)
      marketOffsetSec = TZ_MarketUtcOffsetSeconds(tz, utcNow);

   // market local -> UTC -> server
   int minutes = m - marketOffsetSec / 60 + serverGmtOffsetSec / 60;
   return ((minutes % 1440) + 1440) % 1440;
  }

//+------------------------------------------------------------------+
//| Human readable offset, e.g. "GMT+3" or "GMT-4:30".               |
//+------------------------------------------------------------------+
string TZ_OffsetText(const int offsetSec)
  {
   int total = offsetSec / 60;
   string sign = (total < 0 ? "-" : "+");
   total = MathAbs(total);
   int h = total / 60;
   int m = total % 60;
   if(m == 0)
      return StringFormat("GMT%s%d", sign, h);
   return StringFormat("GMT%s%d:%02d", sign, h, m);
  }

#endif // __XAUUSD_FTMO_TIMEZONES_MQH__
//+------------------------------------------------------------------+
